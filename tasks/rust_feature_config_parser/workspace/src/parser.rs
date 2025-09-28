use crate::error::ConfigError;

#[derive(Debug, PartialEq, Eq)]
pub struct ConfigEntry {
    pub key: String,
    pub value: String,
}

pub fn parse_config(input: &str) -> Result<Vec<ConfigEntry>, ConfigError> {
    if input.is_empty() {
        return Ok(Vec::new());
    }

    Err(ConfigError::InvalidLine(input.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_basic_entries() {
        let entries = parse_config("app.port=8080\nlog.level=INFO").unwrap();
        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0].key, "app.port");
        assert_eq!(entries[0].value, "8080");
    }

    #[test]
    fn trims_whitespace_and_comments() {
        let raw = "  app.name = Demo  \n# comment\nlog.level=info";
        let entries = parse_config(raw).unwrap();
        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0].value, "Demo");
        assert_eq!(entries[1].value, "info");
    }

    #[test]
    fn validates_keys_and_values() {
        let err = parse_config("=value").unwrap_err();
        assert_eq!(err, ConfigError::EmptyKey);

        let err = parse_config("app.port").unwrap_err();
        assert!(matches!(err, ConfigError::InvalidLine(_)));
    }

    #[test]
    fn handles_empty_input() {
        assert!(parse_config("\n  \n").unwrap().is_empty());
    }
}
