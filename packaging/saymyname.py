"""Entry point for the standalone SayMyName app built by PyInstaller.

Built by .github/workflows/release.yml on every version tag.
"""

from namestack.server import main

if __name__ == "__main__":
    main()
