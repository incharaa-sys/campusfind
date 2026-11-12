"""Fill the board with realistic demo reports. Run: python seed.py"""
from datetime import date, timedelta

import app as webapp

D = lambda n: (date.today() - timedelta(days=n)).isoformat()
ITEMS = [
    # kind, title, category, color, description, location, days_ago, name, contact, at_desk
    ("lost", "boAt airdopes", "Earphones", "black", "black case, small scratch on lid, one bud has blue tape", "Library", 1, "Rahul", "98450 11111", 0),
    ("found", "Wireless earbuds in case", "Earphones", "black", "found on 2nd floor reading table, case has a scratch", "Library", 1, "Sneha", "sneha@college.edu", 1),
    ("lost", "ID card with red lanyard", "ID card", "red", "Priya S, CSE 3rd year, lanyard says IEEE", "Canteen", 2, "Priya", "@priya.s", 0),
    ("found", "College ID card", "ID card", "red", "name Priya, found near the juice counter", "Juice Shop", 2, "Arjun", "90080 22222", 1),
    ("lost", "Casio calculator fx-991ES", "Calculator", "grey", "name 'KAVYA' written with marker on back. lost after maths exam", "Exam Hall", 0, "Kavya", "kavya@college.edu", 0),
    ("found", "scientific calc", "Calculator", "grey", "casio, someone wrote a name on the back", "Lecture Hall Complex", 0, "Security", "Security desk", 1),
    ("lost", "Milton steel bottle", "Bottle", "blue", "blue 1 litre flask with a NASA sticker", "Gym", 3, "Vikram", "98860 33333", 0),
    ("found", "Water bottle", "Bottle", "pink", "pink plastic sipper, left on bench", "Basketball Court", 2, "Ananya", "@ananya_k", 0),
    ("lost", "specs in brown case", "Glasses", "brown", "black frame spectacles, Lenskart case", "Computer Lab", 4, "Rohan", "rohan@college.edu", 0),
    ("found", "House keys with Spiderman keychain", "Keys", "silver", "3 keys on a ring", "Parking", 1, "Security", "Security desk", 1),
]

if __name__ == "__main__":
    webapp.init_db()
    with webapp.app.test_request_context():
        db = webapp.db()
        # Clear tables instead of deleting the file: on Windows the .db file
        # is locked while the server is running, so os.remove() would fail.
        db.execute("DELETE FROM matches")
        db.execute("DELETE FROM items")
        db.execute("DELETE FROM sqlite_sequence WHERE name='items'")
        for i, (k, t, c, col, d, loc, ago, n, ct, desk) in enumerate(ITEMS):
            db.execute(
                """INSERT INTO items (kind,title,category,color,description,location,item_date,
                   contact_name,contact,at_desk,owner_code,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (k, t, c, col, d, loc, D(ago), n, ct, desk, f"DEMO{i:02d}", f"{D(ago)}T10:{i:02d}:00"))
        db.commit()
        ids = [r[0] for r in db.execute("SELECT id FROM items WHERE kind='lost'")]
        for i in ids:
            print("matching item", i, "->", webapp.run_matching(i))
    print("Seeded", len(ITEMS), "items. Demo item codes are DEMO00..DEMO09.")
