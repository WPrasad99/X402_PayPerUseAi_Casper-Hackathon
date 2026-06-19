import asyncio
import asyncpg

async def check():
    conn = await asyncpg.connect('postgresql://postgres:1234@localhost:5432/payperai')
    
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'creator_earnings_ledger' ORDER BY ordinal_position"
    )
    print("Columns:", [r['column_name'] for r in rows])
    
    # Add on_chain_tx_id column if missing
    cols = [r['column_name'] for r in rows]
    if 'on_chain_tx_id' not in cols:
        print("Adding on_chain_tx_id column...")
        await conn.execute("ALTER TABLE creator_earnings_ledger ADD COLUMN on_chain_tx_id TEXT DEFAULT NULL")
        print("Done!")
    else:
        print("on_chain_tx_id already exists")
    
    await conn.close()

asyncio.run(check())
