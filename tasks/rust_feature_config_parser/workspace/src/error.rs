use std::fmt;

#[derive(Debug, PartialEq, Eq)]
pub enum ConfigError {
    EmptyKey,
    InvalidLine(String),
}

impl fmt::Display for ConfigError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ConfigError::EmptyKey => write!(f, "key cannot be empty"),
            ConfigError::InvalidLine(line) => write!(f, "invalid line: {}", line),
        }
    }
}

impl std::error::Error for ConfigError {}
