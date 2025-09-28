#[derive(Debug, Clone, PartialEq)]
pub struct Bucket {
    pub start: i64,
    pub end: i64,
    pub count: usize,
    pub average: f64,
    pub min: f64,
    pub max: f64,
}

pub fn bucketize(_points: &[(i64, f64)], _width: i64) -> Vec<Bucket> {
    unimplemented!("bucketize is not implemented")
}
