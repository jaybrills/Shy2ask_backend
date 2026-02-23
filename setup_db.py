import psycopg2
from psycopg2 import sql

def setup_db():
    try:
        # Try to connect as the current user to the default postgres database
        # Often on Linux, the current user has peer auth for a role with the same name
        conn = psycopg2.connect(dbname="postgres")
        conn.autocommit = True
        cur = conn.cursor()
        
        # Create user
        try:
            cur.execute("CREATE USER admin WITH PASSWORD '0000';")
            print("User 'admin' created.")
        except psycopg2.errors.DuplicateObject:
            print("User 'admin' already exists.")
        
        cur.execute("ALTER USER admin WITH SUPERUSER;")
        
        # Create database
        try:
            cur.execute("CREATE DATABASE shy2ask_db OWNER admin;")
            print("Database 'shy2ask_db' created.")
        except psycopg2.errors.DuplicateDatabase:
            print("Database 'shy2ask_db' already exists.")
            
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False

if __name__ == "__main__":
    if not setup_db():
        # Try another way if first one fails
        print("Retrying with user 'postgres'...")
        try:
            conn = psycopg2.connect(dbname="postgres", user="postgres")
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("CREATE USER admin WITH PASSWORD '0000';")
            cur.execute("ALTER USER admin WITH SUPERUSER;")
            cur.execute("CREATE DATABASE shy2ask_db OWNER admin;")
            cur.close()
            conn.close()
            print("Success with postgres user.")
        except Exception as e2:
            print(f"Second attempt failed: {e2}")
