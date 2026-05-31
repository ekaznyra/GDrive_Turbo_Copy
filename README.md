# 🚀 Google Drive Transfer using Google Colab

Transfer files and folders between Google Drive accounts — without downloading or re-uploading — using a free Google Colab notebook.

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/ekaznyra/GDrive_Turbo_Copy/blob/main/GDrive_Turbo_Copy.ipynb)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📖 Description

This project provides a Google Colab notebook that lets you transfer files and folders from one Google Drive account to another without manual downloading and re-uploading. It uses the Google Drive API v3 to perform server-side operations, making transfers fast and efficient regardless of file size.

The notebook includes two tools:

1. **Permission Manager** — Share or unshare files and folders (including Shared Drive content) with another Google account.
2. **Shared with Me Copier** — Copy files and entire folder structures from your "Shared with me" list into your own "My Drive".

## ✅ Key Features

- **Transfer entire folder trees** with subfolders and files preserved
- **Batch processing** with automatic retry and exponential backoff
- **Works with Shared Drives** (Google Workspace) and personal drives
- **Skip existing items** to avoid duplicate copies on re-runs
- **Progress tracking** with real-time progress bars and logging
- **No local software required** — runs entirely in Google Colab
- **Configurable scope** — choose to process files only, folders only, or both

## 🖼 How It Works

```
┌──────────────────┐                          ┌──────────────────┐
│  Source Account   │   Google Drive API v3    │   Destination    │
│  (Google Drive)   │ ──────────────────────▶  │   Account        │
│                   │   Server-side transfer   │   (Google Drive)  │
└──────────────────┘   via Google Colab        └──────────────────┘
```

## 🛠 Tech Stack

| Component        | Technology                                                    |
|------------------|---------------------------------------------------------------|
| Runtime          | [Google Colab](https://colab.research.google.com/)            |
| Language         | Python 3                                                      |
| API              | [Google Drive API v3](https://developers.google.com/drive/api)|
| Authentication   | Google OAuth 2.0 (via `google.colab.auth`)                    |
| Key Libraries    | `google-api-python-client`, `google-auth`, `tqdm`             |

## 📁 Project Structure

```
GDrive_Turbo_Copy/
├── GDrive_Turbo_Copy.ipynb   # Main Colab notebook
├── docs/
│   ├── setup.md                  # Detailed setup guide
│   └── usage.md                  # Usage guide and examples
├── .github/
│   ├── workflows/
│   │   └── validate.yml          # CI workflow for notebook validation
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md         # Bug report template
│   │   └── feature_request.md    # Feature request template
│   └── PULL_REQUEST_TEMPLATE.md  # PR template
├── CONTRIBUTING.md               # Contribution guidelines
├── CHANGELOG.md                  # Version history
├── LICENSE                       # MIT License
├── .gitignore                    # Git ignore rules
└── README.md                     # This file
```

## 🚀 Quick Start

### Prerequisites

- A Google account (source account with files to transfer)
- A Google account (destination account to receive files)
- A web browser with access to [Google Colab](https://colab.research.google.com/)

### Installation

No local installation is required. The notebook runs in the cloud via Google Colab.

1. **Open the notebook** by clicking the badge below:

   [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/ekaznyra/GDrive_Turbo_Copy/blob/main/GDrive_Turbo_Copy.ipynb)

2. **Authenticate** when prompted — sign in with the Google account that has the files you want to transfer.

3. **Configure** the transfer parameters using the interactive form fields.

4. **Run the cells** to start the transfer.

> For detailed step-by-step instructions, see [docs/setup.md](docs/setup.md) and [docs/usage.md](docs/usage.md).

## 📋 Usage Examples

### Example 1: Share a Folder with Another User

1. Open the notebook in Colab
2. Run the **Permission Manager** cell
3. Set **Action** to `Share`
4. Enter the folder path (e.g., `/My Project Folder`)
5. Enter the recipient's email address
6. Choose the role (`writer`, `commenter`, or `reader`)
7. Run the cell

### Example 2: Copy "Shared with Me" Files to Your Drive

1. Open the notebook in Colab
2. Run the **Shared with Me Copier** cell
3. Optionally enter a specific item name (or leave blank to copy all)
4. Enter a destination folder name (or leave blank for root)
5. Run the cell

> See [docs/usage.md](docs/usage.md) for more examples and advanced configuration.

## 🧠 Use Cases

- Moving files before losing access to a school or work account
- Transferring file ownership between personal accounts
- Backing up shared Drive folders to your own account
- Bulk sharing or unsharing files across teams

## 🧪 Testing

Since this project is a Google Colab notebook that interacts with Google Drive APIs, automated unit testing is not directly applicable. The CI workflow validates notebook structure and syntax.

To manually test:

1. Open the notebook in Google Colab
2. Run each cell and verify the output
3. Confirm that files are transferred/shared as expected

## 🤝 Contributing

Contributions are welcome! Please read the [Contributing Guide](CONTRIBUTING.md) for details on how to submit pull requests, report issues, and suggest improvements.


## 🛡 License

This project is licensed under the [MIT License](LICENSE).

## 👤 Author

**ekaznyra**
- GitHub: [@ekaznyra](https://github.com/ekaznyra)
