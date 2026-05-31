# Setup Guide

This guide walks you through setting up and running the Google Drive Transfer notebook.

## Prerequisites

- A **Google account** — You need at least one Google account. For transfers between accounts, you'll need access to both.
- A **web browser** — Any modern browser (Chrome, Firefox, Edge, Safari).
- **Google Colab access** — Free at [colab.research.google.com](https://colab.research.google.com/).

> **Note**: No local software installation is required. Everything runs in the cloud.

## Opening the Notebook

### Option 1: Direct Link

Click the badge to open the notebook directly in Google Colab:

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/ekaznyra/GDrive_Turbo_Copy/blob/main/GDrive_Turbo_Copy.ipynb)

### Option 2: From GitHub

1. Navigate to the [repository on GitHub](https://github.com/ekaznyra/GDrive_Turbo_Copy)
2. Click on `GDrive_Turbo_Copy.ipynb`
3. Click the "Open in Colab" button at the top of the notebook preview

### Option 3: Manual Upload

1. Download `GDrive_Turbo_Copy.ipynb` from the repository
2. Go to [Google Colab](https://colab.research.google.com/)
3. Click **File → Upload notebook**
4. Select the downloaded file

## Authentication

When you run the first code cell, Google Colab will prompt you to authenticate:

1. Click **"Allow"** when asked to connect to Google Drive
2. Select the Google account that contains the files you want to manage
3. Grant the requested permissions

The notebook uses Google's built-in Colab authentication (`google.colab.auth`), which provides secure OAuth 2.0 access to your Google Drive.

### Permissions Needed

The notebook requires access to:

- **Google Drive API** — To list, copy, and manage file permissions
- Your **Google Drive files** — To read source files and write to the destination

> **Security Note**: The notebook runs in Google's infrastructure and uses standard OAuth 2.0 authentication. Your credentials are never stored in the notebook or transmitted to third parties.

## Dependencies

The notebook automatically installs the following Python packages when you run it:

| Package                        | Purpose                          |
|-------------------------------|----------------------------------|
| `google-api-python-client`    | Google Drive API client          |
| `google-auth-httplib2`        | HTTP transport for Google Auth   |
| `google-auth-oauthlib`        | OAuth 2.0 integration            |
| `tqdm`                        | Progress bar display             |

These are installed via `pip` directly in the Colab environment — no manual setup is needed.

## Troubleshooting

### "Permission denied" errors

- Ensure you've authenticated with the correct Google account
- Check that the source files are actually shared with you
- For Shared Drives, verify you have sufficient access level

### "Quota exceeded" errors

- Google Drive API has usage quotas. Wait a few minutes and try again.
- Reduce the number of files being processed at once.
- The notebook includes automatic retry with exponential backoff to handle temporary quota issues.

### Notebook won't open in Colab

- Ensure you're signed in to a Google account
- Try opening in an incognito/private browser window
- Check if your organization blocks Google Colab access

## Next Steps

Once you've set up and authenticated, proceed to [usage.md](usage.md) for detailed instructions on using both tools in the notebook.
