"""Offline Paraformer (sherpa-onnx) shim delegating to unified sherpa_engine."""
import subprocess
from pathlib import Path
import sherpa_engine

WEIGHTS = 'model.int8.onnx'
TOKENS = 'tokens.txt'


def is_model(path):
    return sherpa_engine.is_model(path)


def serve(model_dir):
    sherpa_engine.serve(model_dir, run=subprocess.run)
