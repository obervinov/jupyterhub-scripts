# JupyterHub Image Processing Scripts

This directory contains Python scripts for automated image processing and management on WebDAV storage systems. The scripts are designed to work with JupyterHub environments and provide automated workflows for image enhancement and organization.

## Overview

The repository contains two main Python applications:

1. **Scaler** - Automated image enhancement tool
2. **Mover** - Image organization tool

Both applications use WebDAV for remote storage access and include robust error handling, multi-threading support, and secure credential management.
All secrets and constants values are stored in a Vault KV store. Structure of the KV store is described in the each script's comments.

## Scripts Description

### Scaler Script (`scaler/`)

**Purpose**: An automated image enhancement tool that upscales low-quality images from WebDAV storage.

**Key Features**:
- **Image Processing**: Uses OpenCV to increase image resolution by a factor of 2 using linear interpolation
- **WebDAV Integration**: Connects to a WebDAV server to download, process, and upload images
- **Automated Workflow**: 
  - Scans the `RAW_REMOTE_DIR` directory for images with names starting with `RAW_NAMES_PREFIXES`
  - Downloads matching images to a local temporary directory
  - Scales them up to improve quality using OpenCV
  - Uploads the enhanced images to `UNSORTED_REMOTE_DIR` directory with timestamped filenames
  - Deletes the original raw images after successful processing
- **Multi-threading**: Supports up to 10 concurrent image processing threads for efficiency (to prevent server overload)
- **Continuous Operation**: Runs in a loop, checking for new images every 30 seconds (configurable via `--frequency` parameter)
- **Error Handling**: Includes WebDAV connection error handling with automatic reconnection after network issues

**Dependencies**:
- OpenCV (opencv-python)
- WebDAV client (webdavclient3)
- Custom Vault client for credential management
- Custom logger package

**Vault KV Store Structure**:
_as hierarchical representation:_
```
webdav/
  ├── host_url: <WebDAV server root URL>
  ├── url: <WebDAV user folder full URL>
  ├── username: <WebDAV username>
  └── password: <WebDAV password>
scaler_constants/
  ├── RAW_NAMES_PREFIXES: [<list of prefixes>]
  ├── RAW_REMOTE_DIR: <remote directory for raw images>
  └── UNSORTED_REMOTE_DIR: <remote directory for processed images>
```
_as JSON example:_
```json
{
  "webdav": {
    "host_url": "https://webdav.example.com/remote.php/webdav/",
    "url": "https://webdav.example.com/remote.php/webdav/user_folder/",
    "username": "your_username",
    "password": "your_password"
  },
  "scaler_constants": {
    "RAW_NAMES_PREFIXES": ["Unknown"],
    "RAW_REMOTE_DIR": "data/AI/_raw",
    "UNSORTED_REMOTE_DIR": "data/AI/_unsorted"
  }
}
```

**Usage**:
```bash
cd scaler/
./run.sh
```

### Mover Script (`mover/`)

**Purpose**: A tag-based image organization tool for managing images in Nextcloud storage systems.

**Key Features**:
- **Nextcloud Integration**: Uses Nextcloud Python API for advanced file operations and tag management
- **Tag-Based Organization**: Automatically moves images based on assigned tags with configurable prefix system
- **Automated Workflow**: 
  - Scans the `UNSORTED_REMOTE_DIR` directory for images with assigned tags
  - Extracts tags from each image file using Nextcloud API
  - Moves images to organized directories based on tag names (removes configurable prefix)
  - Automatically removes processed tags from files after successful movement
  - Provides detailed logging of all operations
- **Secure Credential Management**: Uses Vault KV store for storing Nextcloud credentials
- **Production Ready**: Fully functional with comprehensive error handling and logging

**Requirements**:
- **Nextcloud Python API Extension**: This script requires the [Python API](https://github.com/cloud-py-api/nc_py_api) extension to be installed in the Nextcloud instance
- Proper tag structure with configurable parent tag value (e.g., `ai:category` format)

**Dependencies**:
- nc-py-api: Nextcloud Python API client for file operations and tag management
- webdavclient3: WebDAV client (legacy support)
- Custom Vault client for credential management
- Custom logger package

**Vault KV Store Structure**:
_as hierarchical representation:_
```
webdav/
  ├── host_url: <Nextcloud server root URL>
  ├── username: <Nextcloud username>
  └── password: <Nextcloud password>
mover_constants/
  ├── IMAGES_ROOT_DIR: <base directory for organized images>
  ├── UNSORTED_REMOTE_DIR: <source directory for unorganized images>
  └── PARENT_TAG_VALUE: <tag prefix to identify relevant tags (e.g., "ai")>
```
_as JSON example:_
```json
{
  "webdav": {
    "host_url": "https://nextcloud.example.com",
    "username": "your_username",
    "password": "your_password"
  },
  "mover_constants": {
    "IMAGES_ROOT_DIR": "data/AI/organized",
    "UNSORTED_REMOTE_DIR": "data/AI/_unsorted",
    "PARENT_TAG_VALUE": "ai"
  }
}
```

**Tag Format**:
- Tags should follow the pattern `{PARENT_TAG_VALUE}:category` where `category` becomes the folder name
- Example: tag `ai:landscapes` will move files to `IMAGES_ROOT_DIR/landscapes/`
- Only tags with the specified parent value prefix are processed

**Usage**:
```bash
cd mover/
./run.sh
```

## Common Infrastructure

Both scripts share the following infrastructure components:

### Authentication & Security
- **Vault Integration**: Secure credential management using a custom Vault client
- **Environment Variables**: WebDAV credentials stored securely in Vault KV store

### WebDAV Operations
- **Connection Management**: Robust WebDAV client with automatic reconnection
- **Error Handling**: Comprehensive exception handling for network issues
- **File Operations**: Download, upload, and delete operations with verification

### Development Environment
- **Poetry**: Dependency management using Poetry for Python packages
- **Python 3.12**: Modern Python version requirement
- **Execution Scripts**: Simple bash scripts that install Poetry and run the applications in JupyterHub terminals

### Directory Structure
```
images/
├── README.md                 # This documentation
├── mover/                    # Image organization tool
│   ├── pyproject.toml       # Poetry configuration
│   ├── run.sh               # Execution script
│   └── src/
│       └── main.py          # Main application
└── scaler/                   # Image enhancement tool
    ├── pyproject.toml       # Poetry configuration
    ├── run.sh               # Execution script
    └── src/
        └── main.py          # Main application
```

## Getting Started

### Prerequisites
- Python 3.12+
- Access to a WebDAV server
- Vault server with WebDAV credentials configured
- Internet connection for Poetry installation

### Installation & Setup
1. Clone the repository
2. Navigate to the desired script directory (`scaler/` or `mover/`) in JupyterHub terminal
3. Run the setup script: `./run.sh`

### Configuration
- WebDAV credentials are managed through Vault
- Scaler frequency can be adjusted using the `--frequency` parameter
- Thread limits and directory paths are configurable in the source code

## Development Status

- **Scaler**: Production-ready with full functionality
- **Mover**: Production-ready with full functionality

## Notes

Both scripts are fully functional and ready for production use. The scaler script provides automated image enhancement, while the mover script offers tag-based image organization using Nextcloud's advanced API features.