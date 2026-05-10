import re
import xml.etree.ElementTree as ET
from functools import lru_cache

import requests
from flask import Blueprint, jsonify, request

from extensions import limiter
from utils.security import as_string


stores_bp = Blueprint("stores", __name__)

PCSC_EMAP_URL = "https://emap.pcsc.com.tw/EMapSDK.aspx"
STORE_ID_RE = re.compile(r"\d{6}")


def _text(node, tag):
    child = node.find(tag)
    return child.text.strip() if child is not None and child.text else ""


@lru_cache(maxsize=512)
def _fetch_711_store(store_id):
    response = requests.post(
        PCSC_EMAP_URL,
        data={
            "commandid": "SearchStore",
            "city": "",
            "town": "",
            "roadname": "",
            "ID": store_id,
            "StoreName": "",
            "SpecialStore_Kind": "",
            "leftMenuChecked": "",
            "address": "",
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://emap.pcsc.com.tw/emap.aspx",
        },
        timeout=6,
    )
    response.raise_for_status()
    response.encoding = "utf-8"

    root = ET.fromstring(response.text)
    store_node = root.find("GeoPosition")
    if store_node is None:
        return None

    return {
        "id": _text(store_node, "POIID"),
        "name": _text(store_node, "POIName"),
        "address": _text(store_node, "Address"),
        "phone": _text(store_node, "Telno"),
        "openTime": _text(store_node, "OP_TIME"),
        "services": _text(store_node, "StoreImageTitle"),
    }


@stores_bp.route("/api/stores/711", methods=["GET"])
@limiter.limit("120 per hour")
def lookup_711_store():
    raw_store_id = as_string(request.args.get("storeId")).strip()
    match = STORE_ID_RE.search(raw_store_id)
    if not match:
        return jsonify({"error": "請輸入 6 碼 7-11 店號"}), 400

    store_id = match.group(0)
    try:
        store = _fetch_711_store(store_id)
    except (requests.RequestException, ET.ParseError):
        return jsonify({"error": "暫時無法連線 7-11 門市查詢，請稍後再試"}), 502

    if not store:
        return jsonify({"error": "查無此 7-11 店號，請重新確認"}), 404

    return jsonify({"success": True, "store": store})
