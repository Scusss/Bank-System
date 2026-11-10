
import os

from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from flask_session import Session
from supabase import create_client

load_dotenv()

# Database
db = SQLAlchemy()


# Server-side sessions
server_session = Session()


def get_supabase_client():

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_PUBLISHABLE_KEY")

    if not supabase_url or not supabase_key:
        raise RuntimeError(
            "Supabase URL or publishable key is missing."
        )

    return create_client(
        supabase_url,
        supabase_key
    )

def get_supabase_admin_client():

    supabase_url = os.getenv("SUPABASE_URL")
    secret_key = os.getenv("SUPABASE_SECRET_KEY")

    if not supabase_url or not secret_key:
        raise RuntimeError(
            "Supabase administrative configuration is missing."
        )

    return create_client(
        supabase_url,
        secret_key
    )