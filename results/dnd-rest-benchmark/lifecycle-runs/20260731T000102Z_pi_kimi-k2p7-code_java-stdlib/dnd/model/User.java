package dnd.model;

/**
 * A registered user with PBKDF2 password hash and salt.
 */
public class User {
    public final String username;
    public final String role;
    public final String salt;
    public final String hash;

    public User(String username, String role, String salt, String hash) {
        this.username = username;
        this.role = role;
        this.salt = salt;
        this.hash = hash;
    }
}
