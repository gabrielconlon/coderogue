import os

# Headless SDL for CI and local test runs. Must be set before pygame is imported.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
