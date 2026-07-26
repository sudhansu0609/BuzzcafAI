
from fastapi import APIRouter
router=APIRouter(prefix='/projects')
@router.get('/')
def list_projects(): return []
