-- Run in SSMS with an account permitted to create a database.
-- This creates only the database; Alembic creates/version-controls the tables.
USE [master];
GO
IF DB_ID(N'face_emotion') IS NULL
    EXEC(N'CREATE DATABASE [face_emotion]');
GO
