from aiogram import Router

from . import basic

router = Router(name="worker_root")
router.include_router(basic.router)
