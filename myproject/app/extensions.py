from flask_sqlalchemy import SQLAlchemy
import os
from dotenv import load_dotenv
from supabase import create_client

db = SQLAlchemy()

load_dotenv()

supabase = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SECRET_KEY"],
)