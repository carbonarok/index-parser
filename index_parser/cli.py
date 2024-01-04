import click
import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse
from rich.console import Console
from rich.logging import RichHandler
from concurrent.futures import ThreadPoolExecutor
import concurrent
import logging

# Setting up Rich for logging
logging.basicConfig(
    level="INFO", format="%(message)s", datefmt="[%X]", handlers=[RichHandler()]
)
logger = logging.getLogger("rich")

console = Console()
visited_urls = set()

def normalize_url(url):
    """
    Normalizes a URL by removing query parameters and fragments.
    """
    parsed_url = urlparse(url)
    return urlunparse(parsed_url._replace(params='', query='', fragment=''))

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
    soup = BeautifulSoup(response.text, 'html.parser')

    for a_tag in soup.findAll("a"):
        href = a_tag.attrs.get("href")
        if href == "" or href is None or href.startswith('/'):
            continue
        href = normalize_url(urljoin(url, href))
        parsed_href = urlparse(href)
        if domain not in parsed_href.netloc or href in visited_urls:
            continue
        visited_urls.add(href)
        if parsed_href.path.endswith('/'):
            dirs.add(href)
        elif not any(href.endswith(suffix) for suffix in suffixes_to_ignore) and not (href.endswith('.php') and not force_download_php):
            urls.add(href)
    return urls, dirs

def download_file(url, root_download_path):
    """
    Downloads a file given by `url` to `root_download_path`, maintaining the web server's directory structure
    """
    parsed_url = urlparse(url)
    file_path = os.path.join(root_download_path, parsed_url.netloc, parsed_url.path.lstrip('/'))
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

@click.command()
@click.option("--url", help="URL to download and parse.")
@click.option("--download-path", help="Download path for file.")
@click.option("--suffixes-to-ignore", default=[".mp4", ".mov"], multiple=True, help="File suffixes to ignore.")
@click.option("--force-download-php", is_flag=True, help="Force the download of PHP files regardless of server-side execution.")
def main(url, download_path, suffixes_to_ignore, force_download_php):
    """Entrypoint into CLI app."""
    download_from_index(url, download_path, suffixes_to_ignore, force_download_php)

if __name__ == "__main__":
    main()
