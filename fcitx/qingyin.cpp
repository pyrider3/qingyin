#include <fcitx/addonfactory.h>
#include <fcitx/addoninstance.h>
#include <fcitx/addonmanager.h>
#include <fcitx/instance.h>
#include <fcitx/inputcontext.h>
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
public:
    explicit Qingyin(fcitx::Instance *instance) : instance_(instance) {
        const char *runtime = std::getenv("XDG_RUNTIME_DIR");
        if (!runtime) return;
        path_ = std::string(runtime) + "/qingyin-fcitx.sock";
        fd_ = socket(AF_UNIX, SOCK_DGRAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
        if (fd_ < 0) return;
        sockaddr_un addr{}; addr.sun_family = AF_UNIX;
        std::strncpy(addr.sun_path, path_.c_str(), sizeof(addr.sun_path)-1);
        unlink(path_.c_str());
        if (bind(fd_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) return;
        chmod(path_.c_str(), 0600);
        source_ = instance_->eventLoop().addIOEvent(fd_, fcitx::IOEventFlag::In,
            [this](fcitx::EventSourceIO*, int, fcitx::IOEventFlags) {
                char data[60000]; sockaddr_un sender{}; socklen_t size = sizeof(sender);
                ssize_t n = recvfrom(fd_, data, sizeof(data), 0, reinterpret_cast<sockaddr*>(&sender), &size);
                if (n <= 0) return true;
                std::string reply = "no-focus";
                auto *ic = instance_->lastFocusedInputContext();
                if (ic && ic->hasFocus()) {
                    if (ic->capabilityFlags().testAny(fcitx::CapabilityFlag::PasswordOrSensitive)) reply = "sensitive";
                    else { ic->commitString(std::string(data, n)); reply = "ok"; }
                }
                sendto(fd_, reply.data(), reply.size(), 0, reinterpret_cast<sockaddr*>(&sender), size);
                return true;
            });
    }
    ~Qingyin() override { source_.reset(); if(fd_ >= 0) close(fd_); if(!path_.empty()) unlink(path_.c_str()); }
};
class Factory : public fcitx::AddonFactory {
    fcitx::AddonInstance *create(fcitx::AddonManager *manager) override { return new Qingyin(manager->instance()); }
};
FCITX_ADDON_FACTORY(Factory)
