# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.0] - 2025-06-01

### Added

- Interactive GDrive Permission Manager (share/unshare files and folders)
- Interactive "Shared with Me" to My Drive Copier with recursive folder support
- Batch processing with retry logic and exponential backoff
- Support for Shared Drives (Google Workspace)
- Skip-existing-items feature to avoid duplicate copies
- Progress tracking with tqdm progress bars
- Configurable content scope (files only, folders only, or both)
- Configurable sharing roles (writer, commenter, reader)
- MIT License

### Repository Improvements

- Removed duplicate notebook file
- Renamed notebook for clarity (`google_drive_transfer.ipynb`)
- Added comprehensive README with badges, structure overview, and usage examples
- Added contributing guidelines (`CONTRIBUTING.md`)
- Added documentation directory (`docs/`)
- Added GitHub issue and PR templates
- Added CI workflow for notebook validation
- Added `.gitignore` for Python and Jupyter artifacts
