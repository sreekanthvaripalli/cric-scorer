import uvicorn
import os

# Use import string for reload support
uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload=True)
