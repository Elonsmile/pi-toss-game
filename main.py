import os, uuid, random, json, requests

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, Field, create_engine, Session, select
from typing import Optional

# --- Configuration ---
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tossdemo.db")  # Change for Postgres!
PI_API_KEY = os.getenv("PI_API_KEY", "YOUR_PI_PLATFORM_API_KEY")
PI_API_URL = "https://api.minepi.com/v2/payments"
NETLIFY_URL = "https://YOUR-NETLIFY-SITE.netlify.app"

# --- FastAPI & DB Setup ---
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
    id: str = Field(primary_key=True, default_factory=lambda: str(uuid.uuid4())[:8])
    creator: str
    creator_gender: str
    creator_payment_id: str
    bet_amount: float
    status: str = "open"
    players_json: str = Field(default="[]")
    player_genders_json: str = Field(default="[]")
    player_payment_ids_json: str = Field(default="[]")
    winner: Optional[str] = None
    dev_fee: float
    tx_fee: float
    payout: float

# Only run this ONCE (can comment after initial creation for Postgres):
SQLModel.metadata.create_all(engine)


# --- Payment verification ---
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
    return {"message": "Welcome to the Pi Toss Game API!"}

@app.get("/api/open_tables")
def open_tables():
    with Session(engine) as session:
        tables = session.exec(select(GameTable).where(GameTable.status.in_(["open", "full"]))).all()
        # Decode lists for API response
        result = []
        for t in tables:
            td = t.dict()
            td["players"] = json.loads(td.pop("players_json", "[]"))
            td["player_genders"] = json.loads(td.pop("player_genders_json", "[]"))
            td["player_payment_ids"] = json.loads(td.pop("player_payment_ids_json", "[]"))
            result.append(td)
        return {"tables": result}

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
            players_json=json.dumps([data["username"]]),
            player_genders_json=json.dumps([data["gender"]]),
            player_payment_ids_json=json.dumps([data["payment_id"]]),
            dev_fee=float(data["dev_fee"]),
            tx_fee=float(data["tx_fee"]),
            payout=(float(data["bet_amount"])*2) - float(data["dev_fee"]) - float(data["tx_fee"])
        )
        session.add(t)
        session.commit()
        td = t.dict()
        td["players"] = json.loads(td.pop("players_json", "[]"))
        td["player_genders"] = json.loads(td.pop("player_genders_json", "[]"))
        td["player_payment_ids"] = json.loads(td.pop("player_payment_ids_json", "[]"))
        return {"success": True, "table": td}

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
        players = json.loads(t.players_json)
        player_genders = json.loads(t.player_genders_json)
        player_payment_ids = json.loads(t.player_payment_ids_json)
        if username in players:
            raise HTTPException(400, "Already joined")
        players.append(username)
        player_genders.append(gender)
        player_payment_ids.append(payment_id)
        t.players_json = json.dumps(players)
        t.player_genders_json = json.dumps(player_genders)
        t.player_payment_ids_json = json.dumps(player_payment_ids)
        t.status = "full" if len(players) == 2 else "open"
        session.add(t)
        session.commit()
        td = t.dict()
        td["players"] = players
        td["player_genders"] = player_genders
        td["player_payment_ids"] = player_payment_ids
        return {"success": True, "table": td}

@app.post("/api/toss_coin")
def toss_coin(data: dict):
    table_id = data.get("table_id")
    with Session(engine) as session:
        t = session.get(GameTable, table_id)
        if not t or t.status != "full":
            raise HTTPException(400, "Invalid table or not enough players")
        players = json.loads(t.players_json)
        winner_idx = random.randint(0, 1)
        t.winner = players[winner_idx]
        t.status = "completed"
        session.add(t)
        session.commit()
        td = t.dict()
        td["players"] = players
        td["player_genders"] = json.loads(td.pop("player_genders_json", "[]"))
        td["player_payment_ids"] = json.loads(td.pop("player_payment_ids_json", "[]"))
        return {"result": t.winner, "table": td}
