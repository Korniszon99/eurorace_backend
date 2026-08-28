# EuroRace Backend API - Dokumentacja dla Flutter

## Przegląd
API do śledzenia lokalizacji użytkowników w czasie rzeczywistym z obsługą WebSocket i REST endpointów.

---

## Autentykacja i Zarządzanie Użytkownikami

### 1. Rejestracja użytkownika

**Endpoint:** `POST /api/auth/registration/`
**Metoda:** POST
**Autentykacja:** Nie wymagana

**Dane wejściowe:**
```json
{
    "username": "john_doe",
    "email": "john@example.com",
    "password1": "securepassword123",
    "password2": "securepassword123"
}
```

**Parametry:**
- `username`: Nazwa użytkownika (string, wymagane, unikalne)
- `email`: Adres email (string, wymagane, poprawny format email)
- `password1`: Hasło (string, wymagane, minimum 8 znaków)
- `password2`: Potwierdzenie hasła (string, wymagane, musi być identyczne z password1)

**Odpowiedź (sukces):**
```json
{
    "key": "abc123def456ghi789jkl012mno345pqr678stu"
}
```

**Odpowiedź (błąd):**
```json
{
    "username": ["A user with that username already exists."],
    "email": ["Enter a valid email address."],
    "password1": ["This password is too short. It must contain at least 8 characters."]
}
```

### 2. Logowanie użytkownika

**Endpoint:** `POST /api/auth/login/`
**Metoda:** POST
**Autentykacja:** Nie wymagana

**Dane wejściowe:**
```json
{
    "username": "john_doe",
    "password": "securepassword123"
}
```

**Parametry:**
- `username`: Nazwa użytkownika lub email (string, wymagane)
- `password`: Hasło (string, wymagane)

**Odpowiedź (sukces):**
```json
{
    "key": "abc123def456ghi789jkl012mno345pqr678stu",
    "user": {
        "pk": 123,
        "username": "john_doe",
        "email": "john@example.com",
        "first_name": "",
        "last_name": ""
    }
}
```

**Odpowiedź (błąd):**
```json
{
    "non_field_errors": ["Unable to log in with provided credentials."]
}
```

### 3. Wylogowanie użytkownika

**Endpoint:** `POST /api/auth/logout/`
**Metoda:** POST
**Autentykacja:** Wymagana

**Dane wejściowe:** Brak (tylko token w headerze)

**Odpowiedź:**
```json
{
    "detail": "Successfully logged out."
}
```

### 4. Informacje o bieżącym użytkowniku

**Endpoint:** `GET /api/auth/user/`
**Metoda:** GET
**Autentykacja:** Wymagana

**Odpowiedź:**
```json
{
    "pk": 123,
    "username": "john_doe",
    "email": "john@example.com",
    "first_name": "",
    "last_name": ""
}
```

### 5. Aktualizacja profilu użytkownika

**Endpoint:** `PUT /api/auth/user/`
**Metoda:** PUT
**Autentykacja:** Wymagana

**Dane wejściowe:**
```json
{
    "first_name": "John",
    "last_name": "Doe",
    "email": "newemail@example.com"
}
```

**Odpowiedź:**
```json
{
    "pk": 123,
    "username": "john_doe",
    "email": "newemail@example.com",
    "first_name": "John",
    "last_name": "Doe"
}
```

### 6. Zmiana hasła

**Endpoint:** `POST /api/auth/password/change/`
**Metoda:** POST
**Autentykacja:** Wymagana

**Dane wejściowe:**
```json
{
    "old_password": "oldpassword123",
    "new_password1": "newpassword456",
    "new_password2": "newpassword456"
}
```

**Odpowiedź:**
```json
{
    "detail": "New password has been saved."
}
```

### 7. Reset hasła (żądanie)

**Endpoint:** `POST /api/auth/password/reset/`
**Metoda:** POST
**Autentykacja:** Nie wymagana

**Dane wejściowe:**
```json
{
    "email": "john@example.com"
}
```

**Odpowiedź:**
```json
{
    "detail": "Password reset e-mail has been sent."
}
```

### 8. Reset hasła (potwierdzenie)

**Endpoint:** `POST /api/auth/password/reset/confirm/`
**Metoda:** POST
**Autentykacja:** Nie wymagana

**Dane wejściowe:**
```json
{
    "uid": "MjM",
    "token": "5wq-988e9ac58dd2793e7a52",
    "new_password1": "newpassword123",
    "new_password2": "newpassword123"
}
```

**Odpowiedź:**
```json
{
    "detail": "Password has been reset with the new password."
}
```

### Przykład implementacji w Flutter:

```dart
import 'package:http/http.dart' as http;
import 'dart:convert';

class AuthService {
  final String baseUrl = 'https://your-domain/api/auth';
  String? _authToken;

  String? get authToken => _authToken;

  Future<Map<String, dynamic>> register({
    required String username,
    required String email,
    required String password1,
    required String password2,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/registration/'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'username': username,
        'email': email,
        'password1': password1,
        'password2': password2,
      }),
    );

    final data = jsonDecode(response.body);
    
    if (response.statusCode == 201) {
      _authToken = data['key'];
      return data;
    } else {
      throw Exception('Registration failed: ${data.toString()}');
    }
  }

  Future<Map<String, dynamic>> login({
    required String username,
    required String password,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/login/'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'username': username,
        'password': password,
      }),
    );

    final data = jsonDecode(response.body);
    
    if (response.statusCode == 200) {
      _authToken = data['key'];
      return data;
    } else {
      throw Exception('Login failed: ${data.toString()}');
    }
  }

  Future<void> logout() async {
    if (_authToken == null) return;

    final response = await http.post(
      Uri.parse('$baseUrl/logout/'),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Token $_authToken',
      },
    );

    if (response.statusCode == 200) {
      _authToken = null;
    } else {
      throw Exception('Logout failed');
    }
  }

  Future<Map<String, dynamic>> getCurrentUser() async {
    if (_authToken == null) throw Exception('Not authenticated');

    final response = await http.get(
      Uri.parse('$baseUrl/user/'),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Token $_authToken',
      },
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    } else {
      throw Exception('Failed to get user data');
    }
  }

  Future<void> changePassword({
    required String oldPassword,
    required String newPassword1,
    required String newPassword2,
  }) async {
    if (_authToken == null) throw Exception('Not authenticated');

    final response = await http.post(
      Uri.parse('$baseUrl/password/change/'),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Token $_authToken',
      },
      body: jsonEncode({
        'old_password': oldPassword,
        'new_password1': newPassword1,
        'new_password2': newPassword2,
      }),
    );

    if (response.statusCode != 200) {
      final data = jsonDecode(response.body);
      throw Exception('Password change failed: ${data.toString()}');
    }
  }

  Future<void> requestPasswordReset(String email) async {
    final response = await http.post(
      Uri.parse('$baseUrl/password/reset/'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'email': email}),
    );

    if (response.statusCode != 200) {
      final data = jsonDecode(response.body);
      throw Exception('Password reset request failed: ${data.toString()}');
    }
  }
}
```

---

## WebSocket - Śledzenie lokalizacji w czasie rzeczywistym

### Połączenie WebSocket
**URL:** `ws://your-domain/ws/location/`
**Protokół:** WebSocket z JSON

### Wysyłanie lokalizacji do serwera

**Format wiadomości:**
```json
{
    "type": "location_update",
    "latitude": 52.2297,
    "longitude": 21.0122
}
```

**Parametry:**
- `type`: Zawsze "location_update"
- `latitude`: Szerokość geograficzna (float, wymagane)
- `longitude`: Długość geograficzna (float, wymagane)

**Odpowiedź serwera:**
```json
{
    "type": "location_saved",
    "success": true
}
```

### Przykład implementacji w Flutter (WebSocket):
```dart
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';

class LocationWebSocket {
  late WebSocketChannel channel;
  
  void connect(String token) {
    channel = WebSocketChannel.connect(
      Uri.parse('ws://your-domain/ws/location/'),
      protocols: ['your-auth-token-here']
    );
  }
  
  void sendLocation(double latitude, double longitude) {
    final message = {
      'type': 'location_update',
      'latitude': latitude,
      'longitude': longitude,
    };
    channel.sink.add(jsonEncode(message));
  }
}
```

---

## REST API Endpoints

### 1. Pobierz trasę bieżącego użytkownika

**Endpoint:** `GET /api/location-reports/my_track/`
**Metoda:** GET
**Autentykacja:** Wymagana

**Odpowiedź:**
```json
{
    "user_id": 123,
    "username": "john_doe",
    "total_points": 150,
    "start_time": "2025-01-06T10:00:00Z",
    "end_time": "2025-01-06T12:30:00Z",
    "coordinates": [
        {
            "latitude": 52.2297,
            "longitude": 21.0122,
            "timestamp": "2025-01-06T10:00:00Z"
        },
        {
            "latitude": 52.2298,
            "longitude": 21.0123,
            "timestamp": "2025-01-06T10:01:00Z"
        }
    ]
}
```

**Opis pól:**
- `user_id`: ID użytkownika
- `username`: Nazwa użytkownika
- `total_points`: Liczba punktów lokalizacji
- `start_time`: Czas pierwszej lokalizacji
- `end_time`: Czas ostatniej lokalizacji
- `coordinates`: Lista punktów lokalizacji z timestamp'ami

### Przykład implementacji w Flutter:
```dart
import 'package:http/http.dart' as http;
import 'dart:convert';

class LocationService {
  final String baseUrl = 'https://your-domain/api';
  final String authToken;

  LocationService(this.authToken);

  Future<Map<String, dynamic>> getMyTrack() async {
    final response = await http.get(
      Uri.parse('$baseUrl/location-reports/my_track/'),
      headers: {
        'Authorization': 'Token $authToken',
        'Content-Type': 'application/json',
      },
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    } else {
      throw Exception('Failed to load track data');
    }
  }
}
```

### 2. Pobierz trasę konkretnego użytkownika (tylko admini)

**Endpoint:** `GET /api/location-reports/user-track/{user_id}/`
**Metoda:** GET
**Autentykacja:** Wymagana (tylko administratorzy)
**Parametry URL:** `user_id` (integer) - ID użytkownika

**Odpowiedź:** Identyczna jak w przypadku `my_track`

**Błędy:**
- `403 Forbidden`: Brak uprawnień administratora
- `404 Not Found`: Użytkownik nie istnieje

### 3. Pobierz najnowsze lokalizacje wszystkich użytkowników

**Endpoint:** `GET /api/location-reports/latest/`
**Metoda:** GET
**Autentykacja:** Wymagana

**Odpowiedź:**
```json
[
    {
        "location": {
            "type": "Point",
            "coordinates": [21.0122, 52.2297]
        },
        "timestamp": "2025-01-06T12:30:00Z",
        "user": 123
    }
]
```

---

## Integracja z Google Maps w Flutter

### Rysowanie polyline na mapie

```dart
import 'package:google_maps_flutter/google_maps_flutter.dart';

class MapScreen extends StatefulWidget {
  @override
  _MapScreenState createState() => _MapScreenState();
}

class _MapScreenState extends State<MapScreen> {
  GoogleMapController? mapController;
  Set<Polyline> polylines = {};
  LocationService locationService = LocationService('your-token');

  @override
  void initState() {
    super.initState();
    loadUserTrack();
  }

  Future<void> loadUserTrack() async {
    try {
      final trackData = await locationService.getMyTrack();
      final coordinates = trackData['coordinates'] as List;
      
      if (coordinates.isNotEmpty) {
        final polylineCoordinates = coordinates.map((coord) => 
          LatLng(coord['latitude'], coord['longitude'])
        ).toList();

        setState(() {
          polylines.add(
            Polyline(
              polylineId: PolylineId('user_track'),
              color: Colors.blue,
              width: 3,
              points: polylineCoordinates,
            ),
          );
        });
      }
    } catch (e) {
      print('Error loading track: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('Moja trasa')),
      body: GoogleMap(
        onMapCreated: (GoogleMapController controller) {
          mapController = controller;
        },
        polylines: polylines,
        initialCameraPosition: CameraPosition(
          target: LatLng(52.2297, 21.0122), // Warszawa
          zoom: 10,
        ),
      ),
    );
  }
}
```

---

## Kody błędów

- `200 OK`: Sukces
- `400 Bad Request`: Nieprawidłowe dane wejściowe
- `401 Unauthorized`: Brak lub nieprawidłowy token autentykacji
- `403 Forbidden`: Brak uprawnień
- `404 Not Found`: Zasób nie znaleziony
- `500 Internal Server Error`: Błąd serwera

---

## Uwagi implementacyjne

1. **Częstotliwość wysyłania lokalizacji**: Zalecane 1-5 sekund dla dobrej jakości śledzenia
2. **Obsługa offline**: Przechowuj lokalizacje lokalnie i wysyłaj po przywróceniu połączenia
3. **Bateria**: Używaj odpowiednich ustawień GPS w zależności od potrzeb dokładności
4. **Prywatność**: Informuj użytkowników o śledzeniu lokalizacji

---

## Testowanie API

Możesz przetestować endpointy używając narzędzi takich jak Postman lub curl:

```bash
# Pobierz swoją trasę
curl -H "Authorization: Token YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     http://your-domain/api/location-reports/my_track/
```
