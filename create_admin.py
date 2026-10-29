"""Safe first-run administrator creation script.

There is no hard-coded administrator password anywhere in this project.
Run this script once after installation and type the password when asked:

    python create_admin.py
"""

import getpass
import sys

from app import create_app
from extensions import db
from models import Role, User


def main():
    app = create_app({"SEED_ON_START": False})
    with app.app_context():
        print("Create an administrator account for the Smart Parking Management System.")
        username = input("Username: ").strip()
        if not username:
            print("Username cannot be empty.", file=sys.stderr)
            return 1
        if len(username) < 3 or len(username) > 32:
            print("Username must be 3-32 characters.", file=sys.stderr)
            return 1
        if User.query.filter(db.func.upper(User.username) == username.upper()).first():
            print("That username already exists.", file=sys.stderr)
            return 1

        email = input("Email (optional, press Enter to skip): ").strip() or None

        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm password: ")
        if len(password) < 8:
            print("Password must be at least 8 characters.", file=sys.stderr)
            return 1
        if password != confirm:
            print("The passwords do not match.", file=sys.stderr)
            return 1

        user = User(username=username, email=email, role=Role.ADMIN)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        print(f"Administrator '{username}' created successfully. You can now log in.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
