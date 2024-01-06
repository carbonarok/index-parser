import logging
import concurrent
import click
import mimetypes
import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse
from rich.console import Console
from rich.logging import RichHandler
from concurrent.futures import ThreadPoolExecutor


# Setting up Rich for logging
logging.basicConfig(level="INFO", format="%(message)s", datefmt="[%X]", handlers=[RichHandler()])
logger = logging.getLogger("rich")

console = Console()
visited_urls = set()


def normalize_url(url):
    """
    Normalizes a URL by removing query parameters and fragments.
    """
    parsed_url = urlparse(url)
    return urlunparse(parsed_url._replace(params="", query="", fragment=""))


def is_valid(url):
    """
    Checks whether `url` is a valid URL.
    """
    parsed = urlparse(url)
    return bool(parsed.netloc) and bool(parsed.scheme)


def get_all_files(url, suffixes_to_ignore, force_download_php):
    """
    Returns all file and directory URLs on a single `url`
    """
    urls = set()
    dirs = set()
    domain = urlparse(url).netloc
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")

    for a_tag in soup.findAll("a"):
        href = a_tag.attrs.get("href")
        if href == "" or href is None or href.startswith("/"):
            continue
        href = normalize_url(urljoin(url, href))
        parsed_href = urlparse(href)
        if domain not in parsed_href.netloc or href in visited_urls:
            continue
        visited_urls.add(href)
        if parsed_href.path.endswith("/"):
            dirs.add(href)
        elif not any(href.endswith(suffix) for suffix in suffixes_to_ignore) and not (
            href.endswith(".php") and not force_download_php
        ):
            urls.add(href)
    return urls, dirs


def download_file(url, root_download_path):
    """
    Downloads a file given by `url` to `root_download_path`, maintaining the web server's directory structure
    """
    parsed_url = urlparse(url)
    file_path = os.path.join(root_download_path, parsed_url.netloc, parsed_url.path.lstrip("/"))
    directory = os.path.dirname(file_path)

    os.makedirs(directory, exist_ok=True)

    response = requests.get(url, stream=True)
    if response.status_code == 403:
        logger.warning(f"Access forbidden for {url}")
        return

    if not os.path.isdir(file_path):
        with open(file_path, "wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)


def download_from_index(url, root_download_path, suffixes_to_ignore, force_download_php):
    """
    Recursively downloads files from `url`, excluding files with `suffixes_to_ignore`
    """
    files, dirs = get_all_files(url, suffixes_to_ignore, force_download_php)

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_url = {executor.submit(download_file, file, root_download_path): file for file in files}
        for future in concurrent.futures.as_completed(future_to_url):
            file_url = future_to_url[future]
            try:
                future.result()
                logger.info(f"Downloaded {file_url}")
            except Exception as exc:
                logger.error(f"{file_url} generated an exception: {exc}")

    for dir_url in dirs:
        download_from_index(dir_url, root_download_path, suffixes_to_ignore, force_download_php)


def is_binary(file_path):
    """
    Checks if a file is binary based on its MIME type.
    """
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type and mime_type.startswith('application/')


def search_in_file(file_path, search_strings):
    """
    Searches for given strings in a file and logs the line containing each string.
    """
    if is_binary(file_path):
        logger.info(f"Skipping binary file: {file_path}")
        return
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            for line_number, line in enumerate(file, 1):
                if any(search_string in line for search_string in search_strings):
                    logger.info(f"Match found in {file_path}:{line_number}")
                    logger.info(f"Line: {line.strip()}")
    except UnicodeDecodeError:
        try:
            with open(file_path, 'r', encoding='ISO-8859-1') as file:
                for line_number, line in enumerate(file, 1):
                    if any(search_string in line for search_string in search_strings):
                        logger.info(f"Match found in {file_path}:{line_number}")
        except Exception as e:
            logger.error(f"Error reading {file_path}: {e}")


def parse_downloaded_files(download_path, search_strings):
    """
    Parses all downloaded files in the given path for specific strings.
    """
    for root, dirs, files in os.walk(download_path):
        for file in files:
            file_path = os.path.join(root, file)
            search_in_file(file_path, search_strings)


@click.command()
@click.option("--url", help="URL to download and parse.")
@click.option("--download-path", help="Download path for file.")
@click.option("--suffixes-to-ignore", default=[".mp4", ".mov"], multiple=True, help="File suffixes to ignore.")
@click.option(
    "--force-download-php", is_flag=True, help="Force the download of PHP files regardless of server-side execution."
)
@click.option("--search-strings", multiple=True, help="Strings to search for in the downloaded files.")
def main(url, download_path, suffixes_to_ignore, force_download_php, search_strings):
    """Entrypoint into CLI app."""
    download_from_index(url, download_path, suffixes_to_ignore, force_download_php)
    base_url = urlparse(url).netloc
    if search_strings:
        parse_downloaded_files(os.path.join(download_path, base_url), search_strings)


if __name__ == "__main__":
    main()
