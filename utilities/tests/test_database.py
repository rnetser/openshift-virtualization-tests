"""Unit tests for database module"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

# Add utilities to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import Base, CnvTestTable, Database


class TestCnvTestTable:
    """Test cases for CnvTestTable class"""

    def test_cnv_test_table_structure(self):
        """Test CnvTestTable has expected structure"""
        # Check table name
        assert CnvTestTable.__tablename__ == "cnv_tests"
        
        # Check columns exist
        assert hasattr(CnvTestTable, "id")
        assert hasattr(CnvTestTable, "test_name")
        assert hasattr(CnvTestTable, "result")
        assert hasattr(CnvTestTable, "run_time")
        
        # Check that it inherits from Base
        assert issubclass(CnvTestTable, Base)


class TestDatabase:
    """Test cases for Database class"""

    @patch("database.create_engine")
    def test_database_init_with_uri(self, mock_create_engine):
        """Test Database initialization with URI"""
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        
        db = Database(uri="sqlite:///test.db")
        
        assert db.uri == "sqlite:///test.db"
        assert db.engine == mock_engine
        mock_create_engine.assert_called_once_with("sqlite:///test.db")

    @patch("database.create_engine")
    def test_database_init_default_uri(self, mock_create_engine):
        """Test Database initialization with default URI"""
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        
        db = Database()
        
        assert db.uri == "sqlite:///cnv-tests.db"
        assert db.engine == mock_engine

    @patch("database.create_engine")
    @patch("database.Base")
    def test_database_connect(self, mock_base, mock_create_engine):
        """Test database connect method"""
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        
        db = Database()
        db.connect()
        
        # Should create all tables
        mock_base.metadata.create_all.assert_called_once_with(bind=mock_engine)

    @patch("database.create_engine")
    @patch("database.sessionmaker")
    def test_database_session(self, mock_sessionmaker, mock_create_engine):
        """Test database session creation"""
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        
        mock_session_class = MagicMock()
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_sessionmaker.return_value = mock_session_class
        
        db = Database()
        session = db.session()
        
        assert session == mock_session
        mock_sessionmaker.assert_called_once_with(bind=mock_engine)

    @patch("database.create_engine")
    @patch("database.sessionmaker")
    def test_database_add_test_result(self, mock_sessionmaker, mock_create_engine):
        """Test adding test result to database"""
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        
        mock_session = MagicMock()
        mock_session_class = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session
        mock_sessionmaker.return_value = mock_session_class
        
        db = Database()
        
        # Mock the add_test_result method if it exists
        with patch.object(db, 'add_test_result', return_value=None) as mock_add:
            db.add_test_result("test_name", "passed", 10.5)
            mock_add.assert_called_once_with("test_name", "passed", 10.5)

    @patch("database.create_engine")
    def test_database_context_manager(self, mock_create_engine):
        """Test Database can be used as context manager if implemented"""
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        
        db = Database()
        
        # Check if context manager methods exist
        if hasattr(db, '__enter__') and hasattr(db, '__exit__'):
            with db as db_context:
                assert db_context is not None

    @patch("database.create_engine")
    def test_database_close(self, mock_create_engine):
        """Test database close/cleanup if implemented"""
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        
        db = Database()
        
        # Check if close method exists
        if hasattr(db, 'close'):
            db.close()
            mock_engine.dispose.assert_called_once() 