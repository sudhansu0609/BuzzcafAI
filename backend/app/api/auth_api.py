import os
import json
import secrets
import hashlib
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel

router = APIRouter(prefix="/api/auth", tags=["Auth"])

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")
AUTH_FILE = os.path.join(DATA_DIR, "auth_config.json")

DEFAULT_USERS = [
    {
        "id": "user-sudhanshu",
        "name": "Sudhanshu",
        "role": "Master Admin / Creator",
        "avatarIcon": "👑",
        "badgeColor": "linear-gradient(135deg, #6366f1 0%, #a855f7 100%)",
        "passwordHash": None
    },
    {
        "id": "user-guest1",
        "name": "Guest Workspace 1",
        "role": "Standard User",
        "avatarIcon": "👤",
        "badgeColor": "linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%)",
        "passwordHash": None
    },
    {
        "id": "user-team",
        "name": "Media Team Member",
        "role": "Content Producer",
        "avatarIcon": "🎬",
        "badgeColor": "linear-gradient(135deg, #10b981 0%, #059669 100%)",
        "passwordHash": None
    }
]

def _get_auth_config() -> dict:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(AUTH_FILE):
        default_config = {
            "authEnabled": False,
            "globalPasswordHash": None,
            "users": DEFAULT_USERS,
            "activeTokens": {}  # token -> userId
        }
        with open(AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=2)
        return default_config
    
    try:
        with open(AUTH_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
            if "users" not in config or not config["users"]:
                config["users"] = DEFAULT_USERS
            if "activeTokens" not in config or isinstance(config["activeTokens"], list):
                config["activeTokens"] = {}
            return config
    except Exception:
        return {
            "authEnabled": False,
            "globalPasswordHash": None,
            "users": DEFAULT_USERS,
            "activeTokens": {}
        }

def _save_auth_config(config: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(AUTH_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

class LoginRequest(BaseModel):
    userId: Optional[str] = None
    password: Optional[str] = None

class RegisterRequest(BaseModel):
    name: str
    role: Optional[str] = "Custom User"
    avatarIcon: Optional[str] = "👤"
    password: Optional[str] = None

class SetPasswordRequest(BaseModel):
    userId: Optional[str] = None
    currentPassword: Optional[str] = None
    newPassword: str
    authEnabled: Optional[bool] = None

class ToggleAuthRequest(BaseModel):
    authEnabled: bool

@router.get("/users")
def get_users():
    config = _get_auth_config()
    users_list = []
    for u in config.get("users", []):
        users_list.append({
            "id": u["id"],
            "name": u["name"],
            "role": u.get("role", "User"),
            "avatarIcon": u.get("avatarIcon", "👤"),
            "badgeColor": u.get("badgeColor", "linear-gradient(135deg, #ec4899 0%, #8b5cf6 100%)"),
            "hasPassword": u.get("passwordHash") is not None
        })
    return users_list

@router.get("/status")
def get_auth_status(authorization: Optional[str] = Header(None), x_user_id: Optional[str] = Header(None)):
    config = _get_auth_config()
    auth_enabled = config.get("authEnabled", False)
    
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
    
    active_tokens = config.get("activeTokens", {})
    authenticated_user_id = active_tokens.get(token) if token else None
    
    is_authenticated = not auth_enabled
    if auth_enabled:
        is_authenticated = bool(token and token in active_tokens)
        
    return {
        "authEnabled": auth_enabled,
        "hasGlobalPassword": config.get("globalPasswordHash") is not None,
        "isAuthenticated": is_authenticated,
        "authenticatedUserId": authenticated_user_id
    }

@router.post("/login")
def login(req: LoginRequest):
    config = _get_auth_config()
    users = config.get("users", [])
    
    target_user = None
    if req.userId:
        for u in users:
            if u["id"] == req.userId or u["name"].lower() == req.userId.lower():
                target_user = u
                break
                
    if not target_user and len(users) > 0:
        target_user = users[0]
        
    if not target_user:
        raise HTTPException(status_code=404, detail="User account not found")

    # Check user profile password or global password
    user_hash = target_user.get("passwordHash")
    global_hash = config.get("globalPasswordHash")
    expected_hash = user_hash if user_hash is not None else global_hash
    
    if config.get("authEnabled", False) or expected_hash is not None:
        check_password = req.password or ""
        if not check_password or _hash_password(check_password) != expected_hash:
            raise HTTPException(status_code=401, detail=f"Incorrect or missing password for profile '{target_user['name']}'")

    new_token = secrets.token_hex(32)
    config["activeTokens"][new_token] = target_user["id"]
    _save_auth_config(config)

    user_data = {
        "id": target_user["id"],
        "name": target_user["name"],
        "role": target_user.get("role", "User"),
        "avatarIcon": target_user.get("avatarIcon", "👤"),
        "badgeColor": target_user.get("badgeColor", "linear-gradient(135deg, #6366f1 0%, #a855f7 100%)"),
        "hasPassword": user_hash is not None or global_hash is not None
    }
    
    return {
        "success": True,
        "token": new_token,
        "user": user_data,
        "message": f"Welcome back, {target_user['name']}!"
    }

@router.post("/register")
def register(req: RegisterRequest):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")

    config = _get_auth_config()
    users = config.get("users", [])
    
    # Check duplicate
    clean_name = req.name.strip()
    for u in users:
        if u["name"].lower() == clean_name.lower():
            raise HTTPException(status_code=400, detail="User profile with this name already exists")
            
    user_id = f"user-{secrets.token_hex(4)}"
    password_hash = _hash_password(req.password.strip()) if req.password and req.password.strip() else None
    
    new_user = {
        "id": user_id,
        "name": clean_name,
        "role": req.role.strip() if req.role else "Custom User",
        "avatarIcon": req.avatarIcon or "👤",
        "badgeColor": "linear-gradient(135deg, #ec4899 0%, #8b5cf6 100%)",
        "passwordHash": password_hash
    }
    
    users.append(new_user)
    config["users"] = users
    
    new_token = secrets.token_hex(32)
    config["activeTokens"][new_token] = user_id
    _save_auth_config(config)
    
    user_data = {
        "id": new_user["id"],
        "name": new_user["name"],
        "role": new_user["role"],
        "avatarIcon": new_user["avatarIcon"],
        "badgeColor": new_user["badgeColor"],
        "hasPassword": password_hash is not None
    }
    
    return {
        "success": True,
        "token": new_token,
        "user": user_data,
        "message": f"User profile created for {clean_name}"
    }

@router.post("/set-password")
def set_password(req: SetPasswordRequest, x_user_id: Optional[str] = Header(None)):
    config = _get_auth_config()
    user_id = req.userId or x_user_id or "user-sudhanshu"
    
    users = config.get("users", [])
    target_user = None
    for u in users:
        if u["id"] == user_id:
            target_user = u
            break
            
    if not target_user:
        raise HTTPException(status_code=404, detail="User profile not found")

    stored_hash = target_user.get("passwordHash") or config.get("globalPasswordHash")
    if stored_hash:
        if not req.currentPassword or _hash_password(req.currentPassword) != stored_hash:
            raise HTTPException(status_code=401, detail="Current password is incorrect")

    if not req.newPassword or len(req.newPassword.strip()) < 3:
        raise HTTPException(status_code=400, detail="Password must be at least 3 characters")

    new_hash = _hash_password(req.newPassword.strip())
    target_user["passwordHash"] = new_hash
    if target_user["id"] == "user-sudhanshu":
        config["globalPasswordHash"] = new_hash
    
    if req.authEnabled is not None:
        config["authEnabled"] = req.authEnabled
        
    new_token = secrets.token_hex(32)
    config["activeTokens"][new_token] = user_id
    _save_auth_config(config)

    return {"success": True, "token": new_token, "message": f"Password updated for {target_user['name']}"}

@router.post("/toggle")
def toggle_auth(req: ToggleAuthRequest):
    config = _get_auth_config()
    config["authEnabled"] = req.authEnabled
    _save_auth_config(config)
    return {"success": True, "authEnabled": req.authEnabled}

@router.post("/logout")
def logout(authorization: Optional[str] = Header(None)):
    config = _get_auth_config()
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        active_tokens = config.get("activeTokens", {})
        if token in active_tokens:
            del active_tokens[token]
            config["activeTokens"] = active_tokens
            _save_auth_config(config)
    return {"success": True, "message": "Logged out"}

