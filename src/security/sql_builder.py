"""SQL Query Builder - Prevents SQL injection with strict parameterization.

Usage:
    from src.security.sql_builder import SQLBuilder
    builder = SQLBuilder()
    
    # Safe parameterized query
    query, params = builder.build_select(
        table="leads",
        columns=["id", "email", "name"],
        where={"status": "hot", "score": (">=", 50)}
    )
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Allowed SQL operators
ALLOWED_OPERATORS = {"=", "!=", ">=", "<=", ">", "<", "IN", "NOT IN", "LIKE", "NOT LIKE", "IS", "IS NOT"}

# SQL injection patterns to detect
SQL_INJECTION_PATTERNS = [
    r"--",
    r";",
    r"\/\*",
    r"\*\/",
    r"EXEC",
    r"EXECUTE",
    r"UNION\s+SELECT",
    r"DROP\s+TABLE",
    r"INSERT\s+INTO",
    r"DELETE\s+FROM",
    r"UPDATE\s+.*\s+SET",
    r"xp_",
    r"sp_",
]

import re


class SQLInjectionError(Exception):
    """Raised when potential SQL injection is detected."""
    pass


class SQLBuilder:
    """Builds parameterized SQL queries safely."""
    
    def __init__(self):
        self._compiled_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in SQL_INJECTION_PATTERNS
        ]
    
    def _detect_injection(self, value: str) -> bool:
        """Check if value contains potential SQL injection patterns."""
        if not isinstance(value, str):
            return False
        
        for pattern in self._compiled_patterns:
            if pattern.search(value):
                logger.warning(f"Potential SQL injection detected: {value[:50]}...")
                return True
        
        return False
    
    def build_select(
        self,
        table: str,
        columns: List[str] = None,
        where: Dict[str, Any] = None,
        order_by: str = None,
        limit: int = None
    ) -> Tuple[str, List[Any]]:
        """Build a safe SELECT query with parameterized values.
        
        Args:
            table: Table name (must be alphanumeric)
            columns: Column names (must be alphanumeric)
            where: WHERE conditions as dict
            order_by: ORDER BY clause (column name only)
            limit: LIMIT value
            
        Returns:
            Tuple of (query_string, parameters)
        """
        # Validate table name
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table):
            raise ValueError(f"Invalid table name: {table}")
        
        # Validate columns
        if columns:
            for col in columns:
                if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', col):
                    raise ValueError(f"Invalid column name: {col}")
            cols = ", ".join(columns)
        else:
            cols = "*"
        
        query = f"SELECT {cols} FROM {table}"
        params = []
        
        # Build WHERE clause
        if where:
            conditions = []
            for key, value in where.items():
                if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', key):
                    raise ValueError(f"Invalid column name in WHERE: {key}")
                
                if isinstance(value, tuple):
                    op = value[0]
                    val = value[1]
                    if op not in ALLOWED_OPERATORS:
                        raise ValueError(f"Invalid operator: {op}")
                    if self._detect_injection(str(val)):
                        raise SQLInjectionError(f"Potential SQL injection in value: {val}")
                    conditions.append(f"{key} {op} ?")
                    params.append(val)
                else:
                    if self._detect_injection(str(value)):
                        raise SQLInjectionError(f"Potential SQL injection in value: {value}")
                    conditions.append(f"{key} = ?")
                    params.append(value)
            
            query += " WHERE " + " AND ".join(conditions)
        
        # Add ORDER BY
        if order_by:
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_,\s]*$', order_by):
                raise ValueError(f"Invalid ORDER BY clause: {order_by}")
            query += f" ORDER BY {order_by}"
        
        # Add LIMIT
        if limit is not None:
            if not isinstance(limit, int) or limit < 0:
                raise ValueError(f"Invalid LIMIT value: {limit}")
            query += " LIMIT ?"
            params.append(limit)
        
        return query, params
    
    def build_update(
        self,
        table: str,
        updates: Dict[str, Any],
        where: Dict[str, Any]
    ) -> Tuple[str, List[Any]]:
        """Build a safe UPDATE query with parameterized values.
        
        Args:
            table: Table name
            updates: Columns to update
            where: WHERE conditions
            
        Returns:
            Tuple of (query_string, parameters)
        """
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table):
            raise ValueError(f"Invalid table name: {table}")
        
        set_clauses = []
        params = []
        
        for col, value in updates.items():
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', col):
                raise ValueError(f"Invalid column name: {col}")
            if self._detect_injection(str(value)):
                raise SQLInjectionError(f"Potential SQL injection in UPDATE value: {value}")
            set_clauses.append(f"{col} = ?")
            params.append(value)
        
        query = f"UPDATE {table} SET {', '.join(set_clauses)}"
        
        # Build WHERE clause
        if where:
            conditions = []
            for key, value in where.items():
                if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', key):
                    raise ValueError(f"Invalid column name in WHERE: {key}")
                conditions.append(f"{key} = ?")
                params.append(value)
            query += " WHERE " + " AND ".join(conditions)
        
        return query, params
