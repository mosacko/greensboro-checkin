from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from .settings import settings
from .routers import attendance as attendance_router

app = FastAPI(title="Greensboro Check-in")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.get("/", include_in_schema=False)
def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request, "sites": settings.sites})

app.include_router(attendance_router.router, prefix="", tags=["attendance"])
