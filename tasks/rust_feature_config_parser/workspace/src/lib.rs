mod error;
mod parser;

pub use error::ConfigError;
pub use parser::{parse_config, ConfigEntry};
