from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


#  Search Request Model
class Cabin(str, Enum):
    ECONOMY = "economy"
    BUSINESS = "business"
    FIRST = "first"

class SearchFlights(BaseModel):
    origin: str
    destination: str
    date: date 
    passengers: int = Field(gt=0)
    cabin: Cabin
    
    @field_validator("date")
    def validate_date(cls, value):
        if value < date.today():
            raise ValueError("Date should be equal to or greater than current date.")
        return value
    
    
# Search Response Model

class Airport(BaseModel):
    airport_name: str
    airport_code: str
    
    
class Stop(BaseModel):
    airport: Airport
    arrival_datetime: datetime
    departure_datetime: datetime
    
    
class Flight(BaseModel):
    flight_id: str
    provider_reference: str | None = None
    flight_name: str
    origin: Airport
    destination: Airport
    departure_datetime: datetime
    arrival_datetime: datetime
    price: float
    currency: str
    cabin: Cabin
    available_seats: int | None = None
    expires_at: datetime | None = None
    requires_instant_payment: bool | None = None
    payment_required_by: datetime | None = None
    stops: list[Stop]
    
# Book Flights
class BookFlight(BaseModel):
    flight_id: str
    passenger_ids: list[str] = Field(min_length=1)
    
#  Passenger
class Passenger(BaseModel):
    id: str
    title: str
    given_name: str
    family_name: str
    gender: str
    born_on: date
    email: str
    phone_number: str
    
class BookingResult(BaseModel):
    booking_id: str
    booking_reference: str
    status: str
    total_amount: float
    currency: str
    payment_required_by: datetime | None = None