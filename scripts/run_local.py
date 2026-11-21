import uvicorn
import os

# Initialize database before starting the server
from app.database import init_db

init_db()

# Use import string for reload support
uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
