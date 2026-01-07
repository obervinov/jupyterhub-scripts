"""
JupyterHub Image Scaler Script

This script provides automated image enhancement functionality for WebDAV storage systems.
It continuously monitors a specified WebDAV directory for low-quality images and automatically
upscales them using OpenCV image processing techniques.

Main Features:
- Automated scanning of WebDAV directories for images with specific naming patterns
- Image resolution enhancement using OpenCV linear interpolation (2x scale factor)
- Multi-threaded processing for efficient handling of multiple images
- Robust error handling with automatic WebDAV reconnection
- Secure credential management using Vault KV store
- Continuous operation with configurable check frequency

Workflow:
1. Scans the RAW_REMOTE_DIR for images starting with RAW_NAMES_PREFIXES
2. Downloads matching images to local temporary directory
3. Scales up image resolution by factor of 2 using OpenCV
4. Uploads enhanced images to UNSORTED_REMOTE_DIR with timestamped filenames
5. Deletes original raw images after successful processing
6. Repeats the process at configured intervals


Configuration:
- WebDAV credentials: Stored in Vault KV store under 'webdav' secret
  Format: {"url": "https://...", "username": "...", "password": "..."}
- Constants: Configurable via Vault 'scaler_constants' secret
  Format: {
    "RAW_NAMES_PREFIXES": ["raw", "image"],
    "RAW_REMOTE_DIR": "_raw",
    "UNSORTED_REMOTE_DIR": "_unsorted"
  }
- Frequency: Adjustable via --frequency command line parameter (default: 300 seconds)
- Thread limit: Maximum 10 concurrent processing threads
"""

import os
import time
import json
import argparse
import threading
from datetime import datetime
from random import randint
import cv2
import webdav3
from vault import VaultClient
from webdav3.client import Client


# Input arguments
parser = argparse.ArgumentParser(description="Image scaler for WebDAV storage")
parser.add_argument("--frequency", type=int, default=300, help="The frequency of the script checking the WebDAV folder.")
args = parser.parse_args()

# Secrets and credentials
vault = VaultClient()
webdav_secret = vault.kv2engine.read_secret("webdav")
constants_secret = vault.kv2engine.read_secret("scaler_constants")

# WebDAV client
options = {
 'webdav_hostname': webdav_secret['url'],
 'webdav_login':    webdav_secret['username'],
 'webdav_password': webdav_secret['password'],
}
webdav_client = Client(options)

# Constants
RAW_NAMES_PREFIXES = json.loads(constants_secret['RAW_NAMES_PREFIXES'])
RAW_REMOTE_DIR = constants_secret['RAW_REMOTE_DIR']
UNSORTED_REMOTE_DIR = constants_secret['UNSORTED_REMOTE_DIR']
WORKDIR = f"{os.getcwd()}/tmp"
OUTPUT_DIR = f"{os.getcwd()}/output"
THREADS_LIMIT = 10


def webdav_exception_handler(method):
    """
    A decorator that catches the connection error to the WebDAV storage and tries to reconnect.
    """
    def wrapper(*args, **kwargs):
        while True:
            try:
                return method(*args, **kwargs)
            except (webdav3.exceptions.NoConnection, webdav3.exceptions.ConnectionException) as connection_exception:
                print(f"Connection error with reason: {connection_exception}")
                print("Waiting for 3 minutes...")
                time.sleep(180)
                print("Reconnecting to the WebDAV server...")
    return wrapper


@webdav_exception_handler
def get_images_list(raw: str) -> list:
    """
    Get list of images to process from WebDAV folder

    Args:
        raw (str): The path to the raw images directory on the WebDAV server.
    """
    files_for_processing = []
    all_files = webdav_client.list(raw, get_info=True)
    for file in all_files:
        try:
            filename = file['path'].split("/")[-1]
            name_condition = any(filename.startswith(prefix) for prefix in RAW_NAMES_PREFIXES)
            if name_condition and not file['isdir']:
                files_for_processing.append(file['path'])
        except (KeyError, TypeError, AttributeError, IndexError, ValueError) as e:
            print(f"Error processing file entry: {e.__class__.__name__}: {e}. File data: {file}")
    return files_for_processing


@webdav_exception_handler
def download_image(remote_file_path: str, directory: str) -> str:
    """
    Download image from WebDAV folder to local tmp directory

    Args:
        remote_file_path (str): The path to the file on the WebDAV server.
        directory (str): The temporary directory to save the file.
    """
    filename = remote_file_path.split("/")[-1]
    # Remove webdav path prefix
    remote_file_path = f"{RAW_REMOTE_DIR}/{filename}"
    webdav_client.download_sync(remote_path=remote_file_path, local_path=f"{directory}/{filename}")
    print(f"Temproaraly files list: {os.listdir(WORKDIR)}")


@webdav_exception_handler
def upload_image(local_file_path: str, remote_directory: str) -> None:
    """
    Upload image from local tmp directory to WebDAV folder

    Args:
        local_file_path (str): The path to the file on the local machine.
        remote_directory (str): The path to the directory on the WebDAV server.
    """
    filename = local_file_path.split("/")[-1]
    # Remove webdav path prefix
    remote_file_path = f"{remote_directory}/{filename}"
    webdav_client.upload_sync(remote_path=remote_file_path, local_path=local_file_path)
    print(f"Uploaded file: {filename} to {remote_file_path}")
    os.remove(local_file_path)


@webdav_exception_handler
def delete_source_image(remote_file_name: str) -> None:
    """
    Delete source image from WebDAV folder

    Args:
        remote_file_name (str): The name of the image file.
    """
    webdav_client.clean(remote_file_name)
    print(f"File {remote_file_name} has been deleted from the WebDAV server")


def increase_resolution(file_name: str = None, scale_factor: int = 2) -> None:
    """
    Increases the resolution of images in the specified directory.

    Args:
        file_name (str): The name of the image file.
        scale_factor (int): The factor by which the resolution of the images will be increased.
    """
    new_file_name = f'jh_rescaler_{datetime.now().strftime("%Y%m%d%H%M%S")}_{randint(1, 1000)}.png'
    input_file = os.path.join(WORKDIR, file_name)
    output_file = os.path.join(OUTPUT_DIR, new_file_name)
    print(f"Input file for scaler: {input_file}\nOutput file from scaler: {output_file}")

    image = cv2.imread(input_file)
    height, width = image.shape[:2]
    new_height, new_width = int(height * scale_factor), int(width * scale_factor)
    resized_image = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
    cv2.imwrite(output_file, resized_image)

    if os.path.exists(output_file):
        os.remove(input_file)
        print(f"Image {file_name} has been scaled and saved as {new_file_name}")
    else:
        print(f"Error: {output_file} not found")
    return new_file_name


def multi_threading_run(file: str = None) -> None:
    """
    Run the image processing in a separate thread.

    Args:
        file (str): The name of the image file.
    """
    download_image(remote_file_path=file, directory=WORKDIR)
    processed_file = increase_resolution(file_name=file.split("/")[-1])
    upload_image(local_file_path=f"{OUTPUT_DIR}/{processed_file}", remote_directory=UNSORTED_REMOTE_DIR)
    delete_source_image(remote_file_name=f"{RAW_REMOTE_DIR}/{file.split('/')[-1]}")
    print(f"Remote file {file} has been deleted from the WebDAV server")


if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(WORKDIR, exist_ok=True)
    while True:
        thread_poll = []
        objects = get_images_list(raw=RAW_REMOTE_DIR)
        if objects:
            print(f"Found {len(objects)} images for processing\nList: {objects}")
            for item in objects:
                if len(thread_poll) >= THREADS_LIMIT:
                    print(f"Thread limit reached: {THREADS_LIMIT}. Waiting for threads to finish...")
                    for thread in thread_poll:
                        thread.join()
                    thread_poll = []
                scaler_thread = threading.Thread(target=multi_threading_run, args=(item,))
                thread_poll.append(scaler_thread)
                scaler_thread.start()
            for thread in thread_poll:
                thread.join()
            print("All images have been processed")
        else:
            print("Not found any files to process in the WebDAV storage")
        print("Sleeping...")
        time.sleep(args.frequency)
