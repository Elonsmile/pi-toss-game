from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Table(BaseModel):
    id: str
    creator: str
    bet_amount: float
    status: str  # "open", "full", "completed"
    players: List[str]

# In-memory list for demonstration purposes
tables = []

@app.get("/api/open_tables")
def get_open_tables():
    return {"tables": [table for table in tables if table.status == "open"]}

@app.post("/api/create_table")
def create_table(table: Table):
    tables.append(table)
    return {"success": True, "table": table}
