from fastapi import APIRouter, HTTPException, status
from app.models.user import UserCreate, UserLogin, Token, UserResponse
from app.db.mongodb import users_collection
from app.core.security import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate):
    # Kiểm tra email đã tồn tại chưa
    existing_user = await users_collection.find_one({"email": user_data.email})
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email này đã được đăng ký. Vui lòng dùng email khác.",
        )

    # Kiểm tra username đã tồn tại chưa
    existing_username = await users_collection.find_one({"username": user_data.username})
    if existing_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tên người dùng đã tồn tại. Vui lòng chọn tên khác.",
        )

    # Tạo user mới
    hashed_pw = hash_password(user_data.password)
    new_user = {
        "username": user_data.username,
        "email": user_data.email,
        "hashed_password": hashed_pw,
    }
    result = await users_collection.insert_one(new_user)
    user_id = str(result.inserted_id)

    # Tạo JWT token
    access_token = create_access_token(data={"sub": user_id, "email": user_data.email})

    return Token(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse(id=user_id, username=user_data.username, email=user_data.email),
    )


@router.post("/login", response_model=Token)
async def login(credentials: UserLogin):
    # Tìm user theo email
    user = await users_collection.find_one({"email": credentials.email})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email hoặc mật khẩu không đúng.",
        )

    # Xác minh password
    if not verify_password(credentials.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email hoặc mật khẩu không đúng.",
        )

    user_id = str(user["_id"])
    access_token = create_access_token(data={"sub": user_id, "email": user["email"]})

    return Token(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse(id=user_id, username=user["username"], email=user["email"]),
    )
