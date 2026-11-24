"""Specialist architectures and a dependency-free FP32 weight estimate."""

from .features import BIO_TAGS, PAD_ID, RANK_MIN_FEATURES


MAX_PARAMETERS = 5_000_000
MAX_WEIGHT_BYTES = 25_000_000


def _integer(config, key, minimum=1):
    value = config.get(key)
    if type(value) is not int or value < minimum:
        raise ValueError(f"{key} must be an integer of at least {minimum}")
    return value


def parameter_estimate(config):
    """Count parameters including embedding padding rows and all layer biases."""
    span = config["span"]
    rank = config["rank"]
    word_buckets = _integer(span, "word_hash_buckets", 2)
    word_dim = _integer(span, "word_embedding_dim")
    char_buckets = _integer(span, "char_vocab_size", 2)
    char_dim = _integer(span, "char_embedding_dim")
    channels = _integer(span, "char_channels")
    kernel = _integer(span, "char_kernel")
    if kernel % 2 == 0:
        raise ValueError("char_kernel must be odd")
    hidden = _integer(span, "hidden_size")
    _integer(span, "max_tokens")
    _integer(span, "max_chars_per_token")
    rank_features = _integer(rank, "features", RANK_MIN_FEATURES)
    rank_hidden = _integer(rank, "hidden_size")

    embeddings = word_buckets * word_dim + char_buckets * char_dim
    character_cnn = channels * (char_dim * kernel + 1)
    bilstm = 2 * 4 * hidden * (word_dim + channels + hidden + 2)
    span_head = len(BIO_TAGS) * (2 * hidden + 1)
    span_parameters = embeddings + character_cnn + bilstm + span_head
    rank_parameters = rank_hidden * (rank_features + 1) + rank_hidden + 1
    total = span_parameters + rank_parameters
    fp32_bytes = total * 4

    max_parameters = min(_integer(config, "max_parameters"), MAX_PARAMETERS)
    max_weight_bytes = min(_integer(config, "max_weight_bytes"), MAX_WEIGHT_BYTES)
    if total > max_parameters or fp32_bytes > max_weight_bytes:
        raise ValueError("Specialists exceed the combined parameter or FP32 weight budget")
    return {"span": span_parameters, "rank": rank_parameters, "total": total, "fp32_bytes": fp32_bytes}


def build_models(torch, config):
    """Construct FP32 networks with the torch module loaded by the remote runtime."""
    expected = parameter_estimate(config)
    span_config = config["span"]
    rank_config = config["rank"]
    nn = torch.nn

    class SpanTagger(nn.Module):
        def __init__(self):
            super().__init__()
            word_dim = span_config["word_embedding_dim"]
            char_dim = span_config["char_embedding_dim"]
            channels = span_config["char_channels"]
            kernel = span_config["char_kernel"]
            hidden = span_config["hidden_size"]
            self.words = nn.Embedding(span_config["word_hash_buckets"], word_dim, padding_idx=PAD_ID)
            self.characters = nn.Embedding(span_config["char_vocab_size"], char_dim, padding_idx=PAD_ID)
            self.char_cnn = nn.Conv1d(char_dim, channels, kernel, padding=kernel // 2)
            self.context = nn.LSTM(word_dim + channels, hidden, batch_first=True, bidirectional=True)
            self.classifier = nn.Linear(2 * hidden, len(BIO_TAGS))

        def forward(self, word_ids, char_ids, lengths):
            batch, tokens, characters = char_ids.shape
            flat_chars = char_ids.reshape(batch * tokens, characters)
            valid_chars = flat_chars.ne(PAD_ID)
            char_vectors = self.characters(flat_chars).transpose(1, 2)
            char_activations = self.char_cnn(char_vectors).relu()
            # Activations are nonnegative, so invalid positions and empty tokens pool to zero.
            pooled = char_activations.masked_fill(~valid_chars.unsqueeze(1), 0).amax(dim=2)
            token_vectors = torch.cat((self.words(word_ids), pooled.reshape(batch, tokens, -1)), dim=2)
            packed = nn.utils.rnn.pack_padded_sequence(
                token_vectors, lengths, batch_first=True, enforce_sorted=False,
            )
            contextual, _ = self.context(packed)
            padded, _ = nn.utils.rnn.pad_packed_sequence(
                contextual, batch_first=True, total_length=tokens,
            )
            return self.classifier(padded)

    class Ranker(nn.Module):
        def __init__(self):
            super().__init__()
            hidden = rank_config["hidden_size"]
            self.layers = nn.Sequential(nn.Linear(rank_config["features"], hidden), nn.ReLU(), nn.Linear(hidden, 1))

        def forward(self, features):
            return self.layers(features).squeeze(-1)

    models = {"span": SpanTagger().float(), "rank": Ranker().float()}
    for task, model in models.items():
        if sum(parameter.numel() for parameter in model.parameters()) != expected[task]:
            raise RuntimeError(f"{task} parameter estimate does not match the constructed model")
    return models
