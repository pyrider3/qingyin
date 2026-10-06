#include <fcitx/addonfactory.h>
#include <fcitx/addoninstance.h>
#include <fcitx/addonmanager.h>
#include <fcitx/instance.h>
#include <fcitx/inputcontext.h>
#include <fcitx/surroundingtext.h>
#include <fcitx/event.h>
#include <fcitx-utils/utf8.h>
#include <algorithm>
#include <sstream>
#include <iomanip>
#include <fcitx-utils/event.h>
#include <fcitx-utils/capabilityflags.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <unistd.h>
#include <cstring>
#include <cstdlib>
#include <string>
class Qingyin : public fcitx::AddonInstance {
    fcitx::Instance *instance_;
    int fd_ = -1;
    std::string path_;
    std::unique_ptr<fcitx::EventSourceIO> source_;
    std::unique_ptr<fcitx::EventSourceTime> recovery_;
    ino_t socket_inode_ = 0;
    std::unique_ptr<fcitx::HandlerTableEntry<fcitx::EventHandler>> keyWatch_, focusWatch_, surroundingWatch_;
    std::string watched_, watchId_, event_, original_, left_, right_, finalReply_;
    uint64_t expires_ = 0;
    bool confirmed_ = false, pending_ = false;
    uint64_t pendingUntil_ = 0;
    static std::string quote(const std::string &text) {
        std::ostringstream out; out << '"';
        for (unsigned char ch : text) {
            if (ch == '"' || ch == '\\') out << '\\' << char(ch);
            else if (ch < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << unsigned(ch);
            else out << char(ch);
        }
        out << '"'; return out.str();
    }
    static std::string id(fcitx::InputContext *ic) {
        std::ostringstream out;
        for (auto byte : ic->uuid()) out << std::hex << std::setw(2) << std::setfill('0') << unsigned(byte);
        return out.str();
    }
    static bool readable(fcitx::InputContext *ic) {
        return ic && ic->hasFocus() && !ic->capabilityFlags().testAny(fcitx::CapabilityFlag::PasswordOrSensitive)
            && ic->capabilityFlags().test(fcitx::CapabilityFlag::SurroundingText) && ic->surroundingText().isValid();
    }
    void clearWatch() {
        watched_.clear(); watchId_.clear(); event_.clear(); original_.clear(); left_.clear(); right_.clear(); finalReply_.clear(); confirmed_ = false; pending_ = false;
    }
    std::string context(fcitx::InputContext *ic) {
        if (!readable(ic)) return "{\"supported\":false,\"focused\":"+std::string(ic&&ic->hasFocus()?"true":"false")+
            ",\"capable\":"+std::string(ic&&ic->capabilityFlags().test(fcitx::CapabilityFlag::SurroundingText)?"true":"false")+
            ",\"valid\":"+std::string(ic&&ic->surroundingText().isValid()?"true":"false")+",\"program\":"+quote(ic?ic->program():"")+",\"token\":"+quote(ic&&ic->hasFocus()?id(ic):"")+"}";
        const auto &sur = ic->surroundingText();
        auto n = fcitx::utf8::length(sur.text());
        auto begin = sur.cursor() > 512 ? sur.cursor()-512 : 0;
        auto end = std::min<size_t>(n, sur.cursor()+512);
        auto text = sur.text().substr(fcitx::utf8::ncharByteLength(sur.text().begin(), begin),
            fcitx::utf8::ncharByteLength(sur.text().begin(), end)-fcitx::utf8::ncharByteLength(sur.text().begin(), begin));
        return "{\"supported\":true,\"token\":"+quote(id(ic))+",\"text\":"+quote(text)+"}";
    }
    void beginWatch(fcitx::InputContext *ic, const std::string &text, const std::string &event) {
        clearWatch();
        if (!ic || !ic->hasFocus() || ic->capabilityFlags().testAny(fcitx::CapabilityFlag::PasswordOrSensitive)
            || text.size()>4096 || text.empty()) return;
        watched_ = id(ic); watchId_ = std::to_string(fcitx::now(CLOCK_MONOTONIC)); event_ = event; original_ = text;
        expires_ = fcitx::now(CLOCK_MONOTONIC)+60000000;
        if (!readable(ic)) { pending_=true; pendingUntil_=fcitx::now(CLOCK_MONOTONIC)+3000000; return; }
        const auto &sur = ic->surroundingText();
        if (sur.text().size() > 32768) { clearWatch(); return; }
        auto first = std::min(sur.cursor(),sur.anchor()), last = std::max(sur.cursor(),sur.anchor());
        auto b = fcitx::utf8::ncharByteLength(sur.text().begin(), first);
        auto e = fcitx::utf8::ncharByteLength(sur.text().begin(), last);
        left_ = sur.text().substr(0,b); right_ = sur.text().substr(e);
        watched_ = id(ic); watchId_ = std::to_string(fcitx::now(CLOCK_MONOTONIC)); event_ = event; original_ = text;
        expires_ = fcitx::now(CLOCK_MONOTONIC)+60000000;
    }
    std::string watch(fcitx::InputContext *ic) {
        if (watched_.empty()) return "{\"watch\":false}";
        if (!finalReply_.empty()) return finalReply_;
        auto now=fcitx::now(CLOCK_MONOTONIC);
        if (!ic || !ic->hasFocus() || id(ic)!=watched_ || now>expires_
            || ic->capabilityFlags().testAny(fcitx::CapabilityFlag::PasswordOrSensitive)) {
            clearWatch(); return "{\"watch\":false}";
        }
        if (pending_) {
            if (now>pendingUntil_) { clearWatch(); return "{\"watch\":false}"; }
            if (readable(ic)) {
                const auto &sur=ic->surroundingText();
                auto cursor=fcitx::utf8::ncharByteLength(sur.text().begin(),sur.cursor());
                if (sur.text().size()<=32768 && size_t(cursor)>=original_.size()
                    && sur.text().compare(cursor-original_.size(),original_.size(),original_)==0) {
                    left_=sur.text().substr(0,cursor-original_.size());right_=sur.text().substr(cursor);
                    pending_=false;confirmed_=true;
                }
            }
            if (pending_) return "{\"watch\":true,\"confirmed\":false,\"id\":"+quote(watchId_)+
                ",\"event\":"+quote(event_)+",\"original\":"+quote(original_)+",\"edited\":\"\"}";
        }
        if (!readable(ic)) { clearWatch(); return "{\"watch\":false}"; }
        const auto &text = ic->surroundingText().text();
        if (text.size() > 32768 || text.size() < left_.size()+right_.size()
            || text.compare(0,left_.size(),left_)!=0
            || text.compare(text.size()-right_.size(),right_.size(),right_)!=0) {
            clearWatch(); return "{\"watch\":false}";
        }
        auto edited = text.substr(left_.size(),text.size()-left_.size()-right_.size());
        if (edited == original_) confirmed_ = true;
        if ((confirmed_ && edited.empty()) || edited.size() > original_.size()+256) { clearWatch(); return "{\"watch\":false}"; }
        return "{\"watch\":true,\"confirmed\":"+std::string(confirmed_?"true":"false")+
            ",\"id\":"+quote(watchId_)+",\"event\":"+quote(event_)+",\"original\":"+quote(original_)+",\"edited\":"+quote(edited)+"}";
    }
    void connectSocket() {
        source_.reset();
        if (fd_ >= 0) close(fd_);
        fd_ = socket(AF_UNIX, SOCK_DGRAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
        if (fd_ < 0) return;
        sockaddr_un addr{}; addr.sun_family = AF_UNIX;
        std::strncpy(addr.sun_path, path_.c_str(), sizeof(addr.sun_path)-1);
        unlink(path_.c_str());
        if (bind(fd_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) return;
        chmod(path_.c_str(), 0600);
        struct stat st{};
        if (lstat(path_.c_str(), &st) == 0) socket_inode_ = st.st_ino;
        source_ = instance_->eventLoop().addIOEvent(fd_, fcitx::IOEventFlag::In,
            [this](fcitx::EventSourceIO*, int, fcitx::IOEventFlags) {
                char data[60000]; sockaddr_un sender{}; socklen_t size = sizeof(sender);
                ssize_t n = recvfrom(fd_, data, sizeof(data), 0, reinterpret_cast<sockaddr*>(&sender), &size);
                if (n <= 0) return true;
                std::string reply = "no-focus";
                auto *ic = instance_->lastFocusedInputContext();
                const std::string request(data,n);
                if (request == "\x1fqingyin:ping") reply = "pong";
                else if (request == "\x1fqingyin:context") reply = context(ic);
                else if (request == "\x1fqingyin:watch") reply = watch(ic);
                else if (request == "\x1fqingyin:cancel-watch") { clearWatch(); reply="ok"; }
                else if (request.rfind("\x1fqingyin:stop-watch:",0)==0) {
                    // A stale observer may stop after focus loss already cleared the watch.
                    // Always consume this command, but never clear a newer insertion.
                    if (request == "\x1fqingyin:stop-watch:"+watchId_) clearWatch();
                    reply="ok";
                }
                else if (request.rfind("\x1fqingyin:",0)==0 &&
                    (request.rfind("\x1fqingyin:learn:",0)!=0 || request.find('\n')==std::string::npos)) {
                    // Reserved protocol messages must never become application text.
                    reply="invalid-command";
                }
                else if (ic && ic->hasFocus()) {
                    if (ic->capabilityFlags().testAny(fcitx::CapabilityFlag::PasswordOrSensitive)) reply = "sensitive";
                    else {
                        const std::string prefix="\x1fqingyin:learn:";
                        auto newline=request.find('\n');
                        if (request.rfind(prefix,0)==0 && newline!=std::string::npos) {
                            auto text=request.substr(newline+1);
                            beginWatch(ic,text,request.substr(prefix.size(),newline-prefix.size()));
                            ic->commitString(text);
                        } else { clearWatch(); ic->commitString(request); }
                        reply="ok";
                    }
                }
                sendto(fd_, reply.data(), reply.size(), 0, reinterpret_cast<sockaddr*>(&sender), size);
                return true;
            });
    }
public:
    explicit Qingyin(fcitx::Instance *instance) : instance_(instance) {
        const char *runtime = std::getenv("XDG_RUNTIME_DIR");
        if (!runtime) return;
        path_ = std::string(runtime) + "/qingyin-fcitx.sock";
        connectSocket();
        keyWatch_ = instance_->watchEvent(fcitx::EventType::InputContextKeyEvent,fcitx::EventWatcherPhase::PreInputMethod,
            [this](fcitx::Event &event) {
                auto &key=static_cast<fcitx::KeyEvent &>(event);
                if (key.key().sym()==FcitxKey_Return || key.key().sym()==FcitxKey_KP_Enter) {
                    auto reply=watch(key.inputContext());
                    if (!watched_.empty() && confirmed_) {
                        reply.pop_back();finalReply_=reply+",\"finished\":true}";
                        expires_=fcitx::now(CLOCK_MONOTONIC)+5000000;
                    } else clearWatch();
                }
            });
        focusWatch_ = instance_->watchEvent(fcitx::EventType::InputContextFocusOut,fcitx::EventWatcherPhase::PreInputMethod,
            [this](fcitx::Event &event) {
                auto &focus=static_cast<fcitx::InputContextEvent &>(event);
                if (id(focus.inputContext())==watched_ && finalReply_.empty()) clearWatch();
            });
        surroundingWatch_ = instance_->watchEvent(fcitx::EventType::InputContextSurroundingTextUpdated,fcitx::EventWatcherPhase::PreInputMethod,
            [this](fcitx::Event &event) {
                auto *ic=static_cast<fcitx::InputContextEvent &>(event).inputContext();
                if (!watched_.empty() && id(ic)==watched_) (void)watch(ic);
            });
        recovery_ = instance_->eventLoop().addTimeEvent(CLOCK_MONOTONIC,
            fcitx::now(CLOCK_MONOTONIC) + 1000000, 100000,
            [this](fcitx::EventSourceTime *timer, uint64_t) {
                if (!watched_.empty() && fcitx::now(CLOCK_MONOTONIC)>expires_) clearWatch();
                struct stat st{};
                if (lstat(path_.c_str(), &st) < 0) connectSocket();
                timer->setNextInterval(1000000);
                timer->setOneShot();
                return true;
            });
    }
    ~Qingyin() override {
        recovery_.reset(); source_.reset();
        if(fd_ >= 0) close(fd_);
        struct stat st{};
        if(!path_.empty() && lstat(path_.c_str(), &st) == 0 && st.st_ino == socket_inode_) unlink(path_.c_str());
    }
};
class Factory : public fcitx::AddonFactory {
    fcitx::AddonInstance *create(fcitx::AddonManager *manager) override { return new Qingyin(manager->instance()); }
};
FCITX_ADDON_FACTORY(Factory)
