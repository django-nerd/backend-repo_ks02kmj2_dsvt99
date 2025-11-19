import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from database import db, create_document, get_documents
from bson import ObjectId
import smtplib
from email.message import EmailMessage

app = FastAPI(title="White Goods CMS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Utilities
# -----------------------------
class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)


def admin_token_required(x_admin_token: Optional[str] = Header(default=None)):
    admin_token = os.getenv("ADMIN_TOKEN")
    if not admin_token:
        # If not configured, deny admin operations for safety
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN not configured on server")
    if x_admin_token != admin_token:
        raise HTTPException(status_code=401, detail="Invalid admin token")
    return True


# -----------------------------
# Schemas (Pydantic models)
# -----------------------------
class ProductCreate(BaseModel):
    name: str
    brand: str
    description: Optional[str] = None
    price: float = Field(ge=0)
    image_url: Optional[str] = None
    category: Optional[str] = None
    in_stock: bool = True
    features: Optional[List[str]] = []


class Product(ProductCreate):
    id: str


class ContactMessageIn(BaseModel):
    name: str
    email: EmailStr
    message: str


class SiteSettings(BaseModel):
    hero_title: str = "Premium White Goods"
    hero_subtitle: str = "Reliable appliances for every home."
    contact_email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[str] = None


# -----------------------------
# Root & health
# -----------------------------
@app.get("/")
def read_root():
    return {"message": "White Goods CMS API running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = os.getenv("DATABASE_NAME") or ""
            try:
                collections = db.list_collection_names()
                response["collections"] = collections
                response["database"] = "✅ Connected & Working"
                response["connection_status"] = "Connected"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# -----------------------------
# Schema exposure for CMS viewer
# -----------------------------
@app.get("/schema")
def get_schema():
    from schemas import Product as ProductSchema
    from schemas import User as UserSchema
    try:
        from schemas import SiteSettings as SiteSettingsSchema  # type: ignore
    except Exception:
        SiteSettingsSchema = None  # type: ignore

    schemas = {
        "product": ProductSchema.model_json_schema(),
        "user": UserSchema.model_json_schema(),
    }
    if SiteSettingsSchema:
        schemas["sitesettings"] = SiteSettingsSchema.model_json_schema()
    return schemas


# -----------------------------
# Products CRUD
# -----------------------------
@app.get("/api/products", response_model=List[Product])
def list_products():
    docs = get_documents("product")
    result: List[Product] = []
    for d in docs:
        d["id"] = str(d.pop("_id"))
        result.append(Product(**d))
    return result


@app.post("/api/products", response_model=Product, dependencies=[Depends(admin_token_required)])
def create_product(payload: ProductCreate):
    doc = payload.model_dump()
    inserted_id = create_document("product", doc)
    doc_out = {**doc, "id": inserted_id}
    return Product(**doc_out)


@app.put("/api/products/{product_id}", response_model=Product, dependencies=[Depends(admin_token_required)])
def update_product(product_id: str, payload: ProductCreate):
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=400, detail="Invalid product id")
    oid = ObjectId(product_id)
    res = db["product"].update_one({"_id": oid}, {"$set": payload.model_dump()})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    updated = db["product"].find_one({"_id": oid})
    updated["id"] = str(updated.pop("_id"))
    return Product(**updated)


@app.delete("/api/products/{product_id}", dependencies=[Depends(admin_token_required)])
def delete_product(product_id: str):
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=400, detail="Invalid product id")
    oid = ObjectId(product_id)
    res = db["product"].delete_one({"_id": oid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"success": True}


# -----------------------------
# Site settings
# -----------------------------
@app.get("/api/settings", response_model=SiteSettings)
def get_settings():
    doc = db["sitesettings"].find_one({})
    if not doc:
        # seed defaults
        default = SiteSettings()
        create_document("sitesettings", default)
        return default
    doc.pop("_id", None)
    return SiteSettings(**doc)


@app.put("/api/settings", response_model=SiteSettings, dependencies=[Depends(admin_token_required)])
def update_settings(payload: SiteSettings):
    existing = db["sitesettings"].find_one({})
    if not existing:
        create_document("sitesettings", payload)
        return payload
    db["sitesettings"].update_one({"_id": existing["_id"]}, {"$set": payload.model_dump()})
    return payload


# -----------------------------
# Contact form -> SMTP + store
# -----------------------------
@app.post("/api/contact")
def send_contact_message(payload: ContactMessageIn):
    # Store in DB
    create_document("contactmessage", payload)

    # Send email via SMTP if configured
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    to_email = os.getenv("CONTACT_TO_EMAIL") or os.getenv("SMTP_USER")

    sent = False
    error: Optional[str] = None

    if smtp_host and to_email:
        try:
            msg = EmailMessage()
            msg["Subject"] = f"New contact message from {payload.name}"
            msg["From"] = smtp_user or to_email
            msg["To"] = to_email
            msg.set_content(
                f"Name: {payload.name}\nEmail: {payload.email}\n\nMessage:\n{payload.message}"
            )

            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.starttls()
                if smtp_user and smtp_pass:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)
                sent = True
        except Exception as e:
            error = str(e)
    else:
        error = "SMTP not configured on server"

    return {"stored": True, "email_sent": sent, "error": error}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
