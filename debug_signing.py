import os, json, asyncio, aiohttp
from dotenv import dotenv_values
from eth_account import Account
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
    
    print('Expected wallet (from .env):', wallet)
    print('Derived wallet (from private key):', Account.from_key('0x' + pk).address)
    print('Match:', Account.from_key('0x' + pk).address.lower() == wallet.lower())
    
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
            
            print('\n=== EIP712 PAYLOAD ===')
            print('Domain:', eip712['domain'])
            print('Types:', eip712['types'])
            print('PrimaryType:', eip712['primaryType'])
            print('Message:', eip712['message'])
            
            # Sign using our manual hasher
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
            
            print('\n=== SIGNING DEBUG ===')
            print('Domain hash:', domain_hash.hex()[:40])
            print('Struct hash:', struct_hash.hex()[:40])
            print('Digest:', digest.hex()[:40])
            
            private_key_bytes = bytes.fromhex(pk.lstrip('0x'))
            private_key_obj = keys.PrivateKey(private_key_bytes)
            signed = private_key_obj.sign_msg_hash(digest)
            
            print('Signature v:', signed.v)
            print('Signature r:', hex(signed.r)[:20])
            print('Signature s:', hex(signed.s)[:20])
            
            # Try to recover the address from the signature
            print('\n=== RECOVERY ===')
            recovered = Account.recover_message(
                data={'digest': digest},
                signature={'r': signed.r, 's': signed.s, 'v': signed.v + 27}
            )
            print('Recovered address (v+27):', recovered)
            print('Match:', recovered.lower() == wallet.lower())


asyncio.run(main())
