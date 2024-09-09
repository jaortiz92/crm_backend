.
├── app  # Contains the main application files.
│   ├── __init__.py   # this file makes "app" a "Python package"
│   ├── main.py       # Initializes the FastAPI application.
│   ├── dependencies.py # Defines dependencies used by the routers
│   ├── routers
│   │   ├── __init__.py
│   │   ├── items.py  # Defines routes and endpoints related to items.
│   │   └── users.py  # Defines routes and endpoints related to users.
│   ├── crud
│   │   ├── __init__.py
│   │   ├── item.py  # Defines CRUD operations for items.
│   │   └── user.py  # Defines CRUD operations for users.
│   ├── schemas
│   │   ├── __init__.py
│   │   ├── item.py  # Defines schemas for items.
│   │   └── user.py  # Defines schemas for users.
│   ├── models
│   │   ├── __init__.py
│   │   ├── item.py  # Defines database models for items.
│   │   └── user.py  # Defines database models for users.
│   ├── external_services
│   │   ├── __init__.py
│   │   ├── email.py          # Defines functions for sending emails.
│   │   └── notification.py   # Defines functions for sending notifications
│   └── utils
│       ├── __init__.py
│       ├── authentication.py  # Defines functions for authentication.
│       └── validation.py      # Defines functions for validation.
├── tests
│   ├── __init__.py
│   ├── test_main.py
│   ├── test_items.py  # Tests for the items module.
│   └── test_users.py  # Tests for the users module.
├── requirements.txt
├── .gitignore
└── README.md

.
├── app/
│   ├── __init__.py            # Permite que "app" sea tratado como un módulo
│   ├── main.py                # Punto de entrada de la aplicación FastAPI
│   ├── models/
│   │   ├── __init__.py        # Importa todos los modelos aquí
│   │   ├── base.py            # Base model (Declarative Base)
│   │   ├── user.py            # Modelos de la base de datos (ej. User, Post)
│   ├── schemas/
│   │   ├── __init__.py        # Importa todos los esquemas aquí
│   │   ├── user.py            # Esquemas Pydantic (Serialización/Validación)
│   ├── crud/
│   │   ├── __init__.py        # Importa todas las operaciones CRUD aquí
│   │   ├── user.py            # Funciones CRUD (Create, Read, Update, Delete)
│   ├── db/
│   │   ├── __init__.py        # Inicializa la base de datos, configuraciones
│   │   ├── session.py         # Configuración de la sesión de la base de datos
│   │   ├── base.py            # Importa las tablas/models para crear la base de datos
│   ├── api/
│   │   ├── __init__.py        # Importa todas las rutas
│   │   ├── deps.py            # Dependencias comunes (ej. get_db)
│   │   ├── user.py            # Endpoints relacionados con usuarios
│   ├── core/
│   │   ├── __init__.py        # Importa todas las configuraciones aquí
│   │   ├── config.py          # Configuraciones generales de la aplicación
│   │   ├── security.py        # Manejo de seguridad (autenticación, etc.)
│   ├── tests/
│   │   ├── __init__.py        # Permite que "tests" sea tratado como un módulo
│   │   ├── test_user.py       # Tests para los endpoints de usuario
│   │   ├── conftest.py        # Fixtures para pytest, configuración de tests
├── alembic/
│   ├── env.py                 # Configuración de Alembic para las migraciones
│   ├── script.py.mako         # Plantilla para las migraciones
│   ├── versions/              # Archivos de migraciones (autogenerados)
├── .env                       # Variables de entorno (opcional)
├── requirements.txt           # Dependencias del proyecto
├── Dockerfile                 # Configuración de Docker para contenerización
└── README.md                  # Documentación del proyecto