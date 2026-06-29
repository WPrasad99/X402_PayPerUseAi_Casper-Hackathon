import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:1234@localhost:5432/payperai')
    try:
        # Table: services
        try: await conn.execute('ALTER TABLE services RENAME COLUMN price_input_microalgo TO price_input_motes;')
        except Exception as e: print(e)
        try: await conn.execute('ALTER TABLE services RENAME COLUMN price_output_microalgo TO price_output_motes;')
        except Exception as e: print(e)
        
        # Table: used_deposits
        try: await conn.execute('ALTER TABLE used_deposits RENAME COLUMN amount_microalgo TO amount_motes;')
        except Exception as e: print(e)
        
        # Table: creator_profiles
        try: await conn.execute('ALTER TABLE creator_profiles RENAME COLUMN total_earnings_microalgo TO total_earnings_motes;')
        except Exception as e: print(e)
        
        # Table: ai_agents
        try: await conn.execute('ALTER TABLE ai_agents RENAME COLUMN price_per_request_microalgo TO price_per_request_motes;')
        except Exception as e: print(e)
        try: await conn.execute('ALTER TABLE ai_agents RENAME COLUMN price_input_microalgo TO price_input_motes;')
        except Exception as e: print(e)
        try: await conn.execute('ALTER TABLE ai_agents RENAME COLUMN price_output_microalgo TO price_output_motes;')
        except Exception as e: print(e)
        
        # Table: ai_agent_usage
        try: await conn.execute('ALTER TABLE ai_agent_usage RENAME COLUMN cost_microalgo TO cost_motes;')
        except Exception as e: print(e)
        try: await conn.execute('ALTER TABLE ai_agent_usage RENAME COLUMN creator_cut_microalgo TO creator_cut_motes;')
        except Exception as e: print(e)
        try: await conn.execute('ALTER TABLE ai_agent_usage RENAME COLUMN platform_cut_microalgo TO platform_cut_motes;')
        except Exception as e: print(e)
        
        # Table: creator_earnings_ledger
        try: await conn.execute('ALTER TABLE creator_earnings_ledger RENAME COLUMN amount_microalgo TO amount_motes;')
        except Exception as e: print(e)
        
        print("Schema migration completed successfully.")
    except Exception as e:
        print(f"Error during migration: {e}")
    finally:
        await conn.close()

if __name__ == '__main__':
    asyncio.run(main())
