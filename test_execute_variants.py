import os, json, asyncio, aiohttp
from dotenv import dotenv_values
from eth_keys import keys
from eth_utils import keccak


env = dotenv_values('.env')
os.environ.update({k: v for k, v in env.items() if v is not None})


def hash_eip712_struct(primary_type, message, types):
    '''Hash an EIP712 struct'''
    def get_type_string(type_name):
        if type_name not in types:
            return type_name
        fields_data = types[type_name]
        if isinstance(fields_data, list):
            field_strings = [f"{field['type']} {field['name']}" for field in fields_data]
        else:
            field_strings = [f"{field_type} {field_name}" for field_name, field_type in fields_data.items()]
        return f"{type_name}({','.join(field_strings)})"
    
    type_string = get_type_string(primary_type)
    type_hash = keccak(text=type_string)
    
    def encode_field(field_name, field_type, value):
        if field_type == 'string':
            return keccak(text=value)
        if field_type == 'bytes':
            return keccak(value)
        if field_type.startswith('uint'):
            if isinstance(value, str):
                value = int(value)
            return value.to_bytes(32, byteorder='big')
        if field_type == 'address':
            hex_value = str(value).lower().replace('0x', '')
            return bytes.fromhex(hex_value.zfill(40))
        if field_type.startswith('bytes'):
            if isinstance(value, str) and value.startswith('0x'):
                return bytes.fromhex(value[2:])
            if isinstance(value, (bytes, bytearray)):
                return bytes(value)
            return value.encode() if isinstance(value, str) else bytes(value)
        return hash_eip712_struct(field_type, value, types)
    
    encoded_fields = [type_hash]
    fields_data = types.get(primary_type, [])
    if isinstance(fields_data, list):
        for field in fields_data:
            field_name = field['name']
            field_type = field['type']
            encoded_fields.append(encode_field(field_name, field_type, message[field_name]))
    else:
        for field_name, field_type in fields_data.items():
            encoded_fields.append(encode_field(field_name, field_type, message[field_name]))
    
    return keccak(b''.join(encoded_fields))


async def main():
    api_key = os.getenv('NANSEN_API_KEY')
    wallet = os.getenv('PORTFOLIO_WALLET_HYPERLIQUID')
    pk = os.getenv('PORTFOLIO_WALLET_PRIVATE_KEY')
    
    payload = {
        'wallet_address': wallet,
        'coin': 'BTC',
        'is_buy': True,
        'size': 0.000642,
        'price': 77862.0,
        'order_type': 'market',
        'slippage': 0.03,
        'leverage': 1,
    }
    
    async with aiohttp.ClientSession() as session:
        # Prepare
        async with session.post('https://api.nansen.ai/api/v1/perp/order', json=payload, headers={'apikey': api_key, 'Content-Type': 'application/json'}) as resp:
            data = await resp.json()
            action = data['action']
            nonce = data['nonce']
            eip712 = data['eip712']
            
            print('Action (first 400 chars):', json.dumps(action)[:400])
            print('Nonce:', nonce)
            
            # Sign
            types = eip712.get('types', {})
            domain = eip712.get('domain', {})
            primary_type = eip712.get('primaryType')
            message = eip712.get('message', {})
            
            types_with_domain = {
                'EIP712Domain': [
                    {'name': 'chainId', 'type': 'uint256'},
                    {'name': 'name', 'type': 'string'},
                    {'name': 'version', 'type': 'string'},
                    {'name': 'verifyingContract', 'type': 'address'},
                ],
                **types
            }
            
            domain_hash = hash_eip712_struct('EIP712Domain', domain, types_with_domain)
            struct_hash = hash_eip712_struct(primary_type, message, types_with_domain)
            digest = keccak(b'\x19\x01' + domain_hash + struct_hash)
            
            private_key_bytes = bytes.fromhex(pk.lstrip('0x'))
            signed = keys.PrivateKey(private_key_bytes).sign_msg_hash(digest)
            signature = {
                'v': signed.v,
                'r': f'0x{signed.r.to_bytes(32, byteorder="big").hex()}',
                's': f'0x{signed.s.to_bytes(32, byteorder="big").hex()}'
            }
            
            print('Signature v:', signature['v'])
            
            # Try 1: execute without wallet_address (current way)
            execute_payload_v1 = {
                'action': action,
                'nonce': nonce,
                'signature': signature
            }
            
            print('\n=== TRY 1: EXECUTE WITHOUT WALLET_ADDRESS ===')
            async with session.post('https://api.nansen.ai/api/v1/perp/execute', json=execute_payload_v1, headers={'apikey': api_key, 'Content-Type': 'application/json'}) as resp:
                print('Status:', resp.status)
                body = await resp.text()
                print('Response:', body[:600])
            
            # Try 2: execute with wallet_address
            execute_payload_v2 = {
                'wallet_address': wallet,
                'action': action,
                'nonce': nonce,
                'signature': signature
            }
            
            print('\n=== TRY 2: EXECUTE WITH WALLET_ADDRESS ===')
            async with session.post('https://api.nansen.ai/api/v1/perp/execute', json=execute_payload_v2, headers={'apikey': api_key, 'Content-Type': 'application/json'}) as resp:
                print('Status:', resp.status)
                body = await resp.text()
                print('Response:', body[:600])


asyncio.run(main())
