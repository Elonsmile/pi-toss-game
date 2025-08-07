from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, Field, create_engine, Session, select
from typing import List, Optional
import uuid, random, requests, os

# --- Configuration ---
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tossdemo.db")  # change for prod!
PI_API_KEY = os.getenv("PI_API_KEY", "YOUR_PI_PLATFORM_API_KEY")
PI_API_URL = "https://api.minepi.com/v2/payments"
NETLIFY_URL = "https://YOUR-NETLIFY-SITE.netlify.app"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[NETLIFY_URL, "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)
engine = create_engine(DATABASE_URL, echo=False)

# --- Models ---
class GameTable(SQLModel, table=True):
    id: str = Field(primary_key=True, default_factory=lambda:str(uuid.uuid4())[:8])
    creator: str
    creator_gender: str
    creator_payment_id: str
    bet_amount: float
    status: str = "open"
    players: List[str] = []
    player_genders: List[str] = []
    player_payment_ids: List[str] = []
    winner: Optional[str] = None
    dev_fee: float
    tx_fee: float
    payout: float

SQLModel.metadata.create_all(engine)

def verify_pi_payment(payment_id: str, username: str, expected_amount: float):
    headers = {"Authorization": f"Key {PI_API_KEY}"}
    r = requests.get(f"{PI_API_URL}/{payment_id}", headers=headers)
    if r.status_code != 200:
        raise HTTPException(400, "Unable to verify Pi payment")
    info = r.json()
    if info["user"] != username or info["status"] != "COMPLETED":
        raise HTTPException(400, "User mismatch or payment not completed")
    if float(info["amount"]) < expected_amount:
        raise HTTPException(400, "Payment amount too low")
    return info

@app.get("/")
def root():
    return {"message":"Welcome to the Pi Toss Game API!"}

@app.get("/api/open_tables")
def open_tables():
    with Session(engine) as session:
        tables = session.exec(select(GameTable).where(GameTable.status.in_(["open", "full"]))).all()
        return {"tables":[t.dict() for t in tables]}

@app.post("/api/payment_complete")
def payment_complete(data: dict):
    required = ["username", "gender", "payment_id", "bet_amount", "dev_fee", "tx_fee"]
    if not all(data.get(i) for i in required):
        raise HTTPException(400, "Missing field(s) in payment_complete")
    total_expected = float(data["bet_amount"]) + float(data["dev_fee"])/2 + float(data["tx_fee"])/2
    verify_pi_payment(data["payment_id"], data["username"], total_expected)
    with Session(engine) as session:
        t = GameTable(
            creator=data["username"],
            creator_gender=data["gender"],
            creator_payment_id=data["payment_id"],
            bet_amount=float(data["bet_amount"]),
            status="open",
            players=[data["username"]],
            player_genders=[data["gender"]],
            player_payment_ids=[data["payment_id"]],
            dev_fee=float(data["dev_fee"]),
            tx_fee=float(data["tx_fee"]),
            payout=(float(data["bet_amount"])*2) - float(data["dev_fee"]) - float(data["tx_fee"])
        )
        session.add(t)
        session.commit()
        return {"success": True, "table": t.dict()}

@app.post("/api/join_table")
def join_table(data: dict):
    table_id = data.get("table_id")
    username = data.get("username")
    gender = data.get("gender")
    payment_id = data.get("payment_id")
    bet_amount = float(data.get("bet_amount"))
    verify_pi_payment(payment_id, username, bet_amount)
    with Session(engine) as session:
        t = session.get(GameTable, table_id)
        if not t or t.status != "open":
            raise HTTPException(404, "Table not found or not open")
        if username in t.players:
            raise HTTPException(400, "Already joined")
        t.players.append(username)
        t.player_genders.append(gender)
        t.player_payment_ids.append(payment_id)
        t.status = "full" if len(t.players) == 2 else "open"
        session.add(t)
        session.commit()
        return {"success": True, "table": t.dict()}

@app.post("/api/toss_coin")
def toss_coin(data: dict):
    table_id = data.get("table_id")
    with Session(engine) as session:
        t = session.get(GameTable, table_id)
        if not t or t.status != "full":
            raise HTTPException(400, "Invalid table or not enough players")
        winner_idx = random.randint(0,1)
        t.winner = t.players[winner_idx]
        t.status = "completed"
        session.add(t)
        session.commit()
        return {"result": t.winner, "table": t.dict()}
