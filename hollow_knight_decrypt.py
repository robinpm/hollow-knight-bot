"""Hollow Knight save file decryption implementation based on bloodorca/hollow."""

import base64
import struct
from typing import List, Union
from Crypto.Cipher import AES


class HollowKnightDecryptor:
    """Decrypts Hollow Knight save files using the bloodorca/hollow algorithm."""
    
    def __init__(self):
        # C# header that appears at the start of save files
        self.csharp_header = [0, 1, 0, 0, 0, 255, 255, 255, 255, 1, 0, 0, 0, 0, 0, 0, 0, 6, 1, 0, 0, 0]
        
        # AES key used for encryption/decryption
        self.aes_key = 'UKu52ePUBwetZ9wNX88o54dnfKRu0T1l'.encode('utf-8')
    
    def string_to_bytes(self, string: str) -> bytes:
        """Convert string to bytes."""
        return string.encode('utf-8')
    
    def bytes_to_string(self, bytes_data: bytes) -> str:
        """Convert bytes to string."""
        return bytes_data.decode('utf-8')
    
    def aes_decrypt(self, encrypted_data: bytes) -> bytes:
        """AES decrypt and remove PKCS7 padding."""
        cipher = AES.new(self.aes_key, AES.MODE_ECB)
        decrypted = cipher.decrypt(encrypted_data)
        # Remove PKCS7 padding
        padding_length = decrypted[-1]
        return decrypted[:-padding_length]
    
    def remove_header(self, data: bytes) -> bytes:
        """Remove C# header and length prefix from save file."""
        # Remove fixed C# header and ending byte (11)
        data = data[len(self.csharp_header):-1]
        
        # Remove LengthPrefixedString header
        length_count = 0
        for i in range(5):
            length_count += 1
            if (data[i] & 0x80) == 0:
                break
        
        return data[length_count:]
    
    def decode(self, encrypted_data: bytes) -> str:
        """Decode Hollow Knight save file to JSON string."""
        # Make a copy to avoid modifying original
        data = bytearray(encrypted_data)
        
        # Remove header
        data = self.remove_header(data)
        
        # Decode base64
        data = base64.b64decode(data)
        
        # AES decrypt
        data = self.aes_decrypt(data)
        
        # Convert to string
        return self.bytes_to_string(data)


def decrypt_hollow_knight_save(file_content: bytes) -> str:
    """Decrypt a Hollow Knight save file and return the JSON string."""
    decryptor = HollowKnightDecryptor()
    return decryptor.decode(file_content)
