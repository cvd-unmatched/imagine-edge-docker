"""
Sony "Send to Smartphone" SOAP/UPnP client.

Adapted from the original imaging-edge.py CLI script (same repo, root directory):
https://github.com/schorschii/ImagingEdge4Linux

Ported as-is except for: dropping the GLib/Notify desktop-notification and
PICTURES_DIR bits (no desktop environment in the container), and routing
progress through an on_event callback instead of print()/argparse.
"""

import os
from typing import Callable, Optional
from urllib.parse import unquote, urlparse
from xml.dom import minidom

import requests


class GetContentException(Exception):
    pass


class ImagingEdge:
    ROOT_DIR_PUSH = "PushRoot"
    ROOT_DIR_PULL = "PhotoRoot"

    def __init__(self, address: str, port: str, output_dir: str):
        self.address = address
        self.port = port
        self.output_dir = output_dir
        self.on_event: Callable[..., None] = lambda *args, **kwargs: None

        self.downloaded = 0
        self.skipped = 0
        self.seen = 0

    def _emit(self, type_: str, message: str, current_file: Optional[str] = None):
        self.on_event(type_, message, current_file=current_file)

    def startTransfer(self):
        self._emit("transfer_start", "Starting transfer")
        requests.post(
            f"http://{self.address}:{self.port}/upnp/control/XPushList",
            headers={
                "SOAPACTION": '"urn:schemas-sony-com:service:XPushList:1#X_TransferStart"',
                "Content-Type": 'text/xml; charset="utf-8"',
            },
            data=(
                '<?xml version="1.0" encoding= "UTF-8"?>'
                '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
                "<s:Body>"
                '<u:X_TransferStart xmlns:u="urn:schemas-sony-com:service:XPushList:1"></u:X_TransferStart>'
                "</s:Body>"
                "</s:Envelope>"
            ),
            timeout=10,
        )

    def endTransfer(self):
        requests.post(
            f"http://{self.address}:{self.port}/upnp/control/XPushList",
            headers={
                "SOAPACTION": '"urn:schemas-sony-com:service:XPushList:1#X_TransferEnd"',
                "Content-Type": 'text/xml; charset="utf-8"',
            },
            data=(
                '<?xml version="1.0" encoding= "UTF-8"?>'
                '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
                "<s:Body>"
                '<u:X_TransferEnd xmlns:u="urn:schemas-sony-com:service:XPushList:1">'
                "<ErrCode>0</ErrCode>"
                "</u:X_TransferEnd>"
                "</s:Body>"
                "</s:Envelope>"
            ),
            timeout=10,
        )
        self._emit("transfer_end", "Transfer ended")

    def getDirectoryContent(self, dir, dirname, downloadSize=None, startingIndex=0):
        response = requests.post(
            f"http://{self.address}:{self.port}/upnp/control/ContentDirectory",
            headers={
                "SOAPACTION": '"urn:schemas-upnp-org:service:ContentDirectory:1#Browse"',
                "Content-Type": 'text/xml; charset="utf-8"',
            },
            data=(
                '<?xml version="1.0"?>'
                '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
                "<s:Body>"
                '<u:Browse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">'
                f"<ObjectID>{dir}</ObjectID>"
                "<BrowseFlag>BrowseDirectChildren</BrowseFlag>"
                "<Filter>*</Filter>"
                f"<StartingIndex>{startingIndex}</StartingIndex>"
                "<RequestedCount>9999</RequestedCount>"
                "<SortCriteria></SortCriteria>"
                "</u:Browse>"
                "</s:Body>"
                "</s:Envelope>"
            ),
            timeout=30,
        )
        if response.status_code != 200:
            raise GetContentException(f"Failed to get dir content: {dir}")

        dom = minidom.parseString(response.text)
        for element in dom.getElementsByTagName("Result"):
            # the <Result> text node is itself an XML document, so parse it a second time
            dom2 = minidom.parseString(element.firstChild.nodeValue)

            for element2 in dom2.getElementsByTagName("container"):
                subdirname = element2.getElementsByTagName("dc:title")[0].firstChild.nodeValue
                self._emit("enter_dir", f"Entering subdir: {subdirname}")
                self.getDirectoryContent(element2.attributes["id"].value, subdirname, downloadSize)

            for element2 in dom2.getElementsByTagName("item"):
                filename = element2.getElementsByTagName("dc:title")[0].firstChild.nodeValue
                filepath = os.path.join(self.output_dir, dirname, filename)

                url = None
                elements3 = element2.getElementsByTagName("res")
                if not downloadSize:
                    lastSize = 0
                    for element3 in elements3:
                        size = 0
                        if "size" in element3.attributes:
                            size = int(element3.attributes["size"].value)
                        if size > lastSize:
                            url = element3.firstChild.nodeValue
                            lastSize = size
                # fallback 1: no item found with size property set, probably a RAW file,
                # search for the largest thumbnail
                if not url:
                    searchSize = downloadSize or "_LRG"
                    for element3 in elements3:
                        if (
                            "protocolInfo" in element3.attributes
                            and searchSize in element3.attributes["protocolInfo"].value
                        ):
                            url = element3.firstChild.nodeValue
                            break
                # fallback 2: use the last <res> as this is most likely the best quality
                if not url:
                    if elements3 and elements3[-1].firstChild.nodeValue:
                        url = elements3[-1].firstChild.nodeValue

                self.seen += 1
                if url:
                    self.downloadFile(url, filepath, filename)
                else:
                    self._emit("warning", f"Unable to find a download candidate: {filename}", current_file=filename)

        numberReturned = int(dom.getElementsByTagName("NumberReturned")[0].firstChild.nodeValue)
        totalMatches = int(dom.getElementsByTagName("TotalMatches")[0].firstChild.nodeValue)
        if startingIndex + numberReturned < totalMatches:
            self.getDirectoryContent(dir, dirname, downloadSize, startingIndex + numberReturned)

    def downloadFile(self, url, filepath=None, filename=None):
        if not filepath:
            filepath = os.path.join(self.output_dir, unquote(urlparse(url).path))
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        with requests.get(url, stream=True, timeout=30) as r:
            if r.status_code != 200:
                self._emit("warning", f"Got unexpected status code {r.status_code}: {url}", current_file=filename)
                return

            length = int(r.headers.get("content-length", 0))
            # skip if the file already exists and is fully downloaded (exact size match)
            if os.path.isfile(filepath) and length != 0 and length == os.stat(filepath).st_size:
                self.skipped += 1
                self._emit("skip", f"Skip existing file: {filename or filepath}", current_file=filename or filepath)
                return

            self._emit("download_start", f"Downloading: {filename or filepath}", current_file=filename or filepath)
            written = 0
            with open(filepath, "wb") as f:
                for chunk in r.iter_content(chunk_size=16384):
                    f.write(chunk)
                    written += len(chunk)

            if length != 0 and length != written:
                # can happen if the download was aborted, or if the file was deleted on the
                # SD card but the image is still in the camera's internal database
                self._emit(
                    "warning",
                    f"Bytes received do not match advertised content-length: {written} <> {length}",
                    current_file=filename or filepath,
                )
            else:
                self.downloaded += 1
                self._emit("download_done", f"Downloaded: {filename or filepath}", current_file=filename or filepath)
