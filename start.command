#!/usr/bin/env bash
# macOS: dubbelklik in Finder. Opent een Terminal-venster dat de app draait; sluit je
# dat venster, dan stopt de app.
exec "$(dirname "$0")/start.sh"
