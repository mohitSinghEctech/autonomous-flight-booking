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
    flight_name: str
    origin: Airport
    destination: Airport
    departure_datetime: datetime
    arrival_datetime: datetime
    price: float
    currency: str
    cabin: Cabin
    available_seats: int
    stops: list[Stop]
    
# Book Flights
class BookFlight(BaseModel):
    flight_id: str
    passengers: int = Field(gt=0)