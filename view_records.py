import sqlite3

def view_approved_vendors():
    print("\nAccessing Secure Database...")
    
    # Connect to the database file we created in app.py
    conn = sqlite3.connect('vendor_compliance.db')
    cursor = conn.cursor()
    
    # Pull all the records from the vault
    try:
        cursor.execute("SELECT * FROM approved_vendors")
        rows = cursor.fetchall()
        
        if not rows:
            print("\n📭 The database is currently empty. No vendors have been approved yet.")
        else:
            print("\n🏢 APPROVED VENDORS SECURE LEDGER 🏢")
            print("=" * 80)
            for row in rows:
                # row[0] is ID, row[1] is Name, row[2] is Tax ID, etc.
                vendor_name = row[1]
                tax_id = row[2]
                expires = row[4]
                liability = row[5]
                
                print(f"ID: {row[0]:<3} | Vendor: {vendor_name:<20} | Tax ID: {tax_id:<12} | Expires: {expires:<12} | Liability: ${liability:,}")
            print("=" * 80)
            print(f"Total Approved Vendors: {len(rows)}\n")
            
    except sqlite3.OperationalError:
        print("\n❌ ERROR: The database doesn't exist yet. Run app.py and APPROVE a vendor first!")
        
    finally:
        conn.close()

if __name__ == "__main__":
    view_approved_vendors()