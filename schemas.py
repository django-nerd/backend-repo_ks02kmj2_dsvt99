"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Product -> "product" collection
- SiteSettings -> "sitesettings" collection
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List


class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Email address")
    address: str = Field(..., description="Address")
    age: Optional[int] = Field(None, ge=0, le=120, description="Age in years")
    is_active: bool = Field(True, description="Whether user is active")


class Product(BaseModel):
    name: str = Field(..., description="Product name")
    brand: str = Field(..., description="Brand name")
    description: Optional[str] = Field(None, description="Product description")
    price: float = Field(..., ge=0, description="Price in dollars")
    image_url: Optional[str] = Field(None, description="Primary image URL")
    category: Optional[str] = Field(None, description="Product category")
    in_stock: bool = Field(True, description="Whether product is in stock")
    features: Optional[List[str]] = Field(default_factory=list, description="Key features list")


class SiteSettings(BaseModel):
    hero_title: str = Field("Premium White Goods", description="Homepage hero title")
    hero_subtitle: str = Field("Reliable appliances for every home.", description="Homepage subtitle")
    contact_email: Optional[EmailStr] = Field(None, description="Where contact form messages go")
    phone: Optional[str] = Field(None, description="Contact phone number")
    address: Optional[str] = Field(None, description="Business address")
