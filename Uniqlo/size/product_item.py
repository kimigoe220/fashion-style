from dotenv import load_dotenv
load_dotenv()

import os, re
from supabase import create_client

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

resp = sb.table("product_items").select("*").limit(1).execute()
row = (resp.data or [{}])[0]

print("product_items 欄位：")
for k in row.keys():
    print("-", k)