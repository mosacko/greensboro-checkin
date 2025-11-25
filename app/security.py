# app/security.py
import bcrypt

def verify_password(plain_password, hashed_password):
    # Check if the password matches the hash
    # Both must be encoded to bytes for bcrypt
    # hashed_password might come from DB as string, so we encode it
    return bcrypt.checkpw(
        plain_password.encode('utf-8'), 
        hashed_password.encode('utf-8')
    )

def get_password_hash(password):
    # Generate a salt and hash the password
    # Returns a string decoded from bytes
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode('utf-8')