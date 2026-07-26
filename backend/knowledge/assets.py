import os
import json
import uuid
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

logger = logging.getLogger("buzzcaf_ai.services.assets")

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
CATALOG_PATH = os.path.join(ASSETS_DIR, "catalog.json")

class AssetService:
    def __init__(self):
        self.catalog: List[Dict[str, Any]] = []
        self.load_catalog()

    def load_catalog(self):
        if not os.path.exists(CATALOG_PATH):
            os.makedirs(os.path.dirname(CATALOG_PATH), exist_ok=True)
            self.catalog = []
            self.save_catalog()
            return
        
        try:
            with open(CATALOG_PATH, "r", encoding="utf-8") as f:
                self.catalog = json.load(f)
        except Exception as e:
            logger.error(f"Error loading asset catalog JSON: {e}")
            self.catalog = []

    def save_catalog(self):
        try:
            os.makedirs(os.path.dirname(CATALOG_PATH), exist_ok=True)
            with open(CATALOG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.catalog, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving asset catalog: {e}")

    def register_asset(self, 
                       title: str, 
                       asset_type: str, 
                       tags: List[str], 
                       file_path: str, 
                       source: str = "internal", 
                       license_info: str = "Royalty Free", 
                       status: str = "active",
                       project_id: Optional[str] = None) -> Dict[str, Any]:
        """Registers a new asset in the system catalog."""
        self.load_catalog()
        
        # Verify asset type is valid
        valid_types = [
            "stock_video", "ai_image", "thumbnail", "sound_effect", 
            "music", "font", "logo", "icon", "motion_graphic", 
            "video_template", "lut", "b_roll", "animation_file"
        ]
        
        normalized_type = asset_type.lower().strip().replace(" ", "_")
        if normalized_type not in valid_types:
            normalized_type = "other"

        # Enforce naming: asset_type_subject_version
        subject_clean = "".join([c for c in title.lower().replace(" ", "_") if c.isalnum() or c == "_"])
        asset_id = f"{normalized_type}_{subject_clean}_v1"
        
        # Format the file path to enforce name convention
        dir_name = os.path.dirname(file_path)
        orig_ext = os.path.splitext(file_path)[1] or ".png"
        new_filename = f"{asset_id}{orig_ext}"
        enforced_path = os.path.join(dir_name, new_filename) if dir_name else new_filename
        enforced_path = enforced_path.replace("\\", "/")
        
        new_asset = {
            "id": asset_id,
            "title": title,
            "type": normalized_type,
            "tags": [t.lower().strip() for t in tags],
            "source": source,
            "license": license_info,
            "creation_date": datetime.now().isoformat(),
            "used_in_projects": [project_id] if project_id else [],
            "status": status,
            "file_path": enforced_path
        }

        
        self.catalog.append(new_asset)
        self.save_catalog()
        logger.info(f"Registered new asset: {asset_id} ({normalized_type})")
        return new_asset

    def query_assets(self, 
                     asset_type: Optional[str] = None, 
                     tag: Optional[str] = None, 
                     query_string: Optional[str] = None) -> List[Dict[str, Any]]:
        """Query and search catalog assets."""
        self.load_catalog()
        results = self.catalog
        
        if asset_type:
            results = [a for a in results if a["type"] == asset_type.lower().strip()]
            
        if tag:
            results = [a for a in results if tag.lower().strip() in a["tags"]]
            
        if query_string:
            qs = query_string.lower().strip()
            results = [a for a in results if qs in a["title"].lower() or any(qs in t for t in a["tags"])]
            
        return results

    def find_similar_asset(self, asset_type: str, tags: List[str], threshold: float = 0.75) -> Optional[Dict[str, Any]]:
        """Checks if a highly matching asset is already registered in the catalog to prevent duplicate generations."""
        self.load_catalog()
        input_tags = set([t.lower().strip() for t in tags])
        if not input_tags:
            return None
            
        for asset in self.catalog:
            if asset["type"] == asset_type.lower().strip():
                asset_tags = set(asset["tags"])
                intersection = input_tags.intersection(asset_tags)
                union = input_tags.union(asset_tags)
                if not union:
                    continue
                similarity = len(intersection) / len(union)
                if similarity >= threshold:
                    logger.info(f"Deduplication: Found similar asset {asset['id']} with {similarity:.2f} tag similarity.")
                    return asset
        return None

asset_service = AssetService()

