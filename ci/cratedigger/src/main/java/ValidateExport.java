import java.io.File;
import java.util.List;
import org.deepsymmetry.cratedigger.Database;
import org.deepsymmetry.cratedigger.pdb.RekordboxPdb;

/**
 * Opens a generated export.pdb with crate-digger's independent DeviceSQL
 * parser and checks the row counts the caller expects.
 *
 * Usage: ValidateExport <export.pdb> <expectedTracks> <expectedPlaylists>
 * Exit code is non-zero if the file cannot be parsed or counts differ.
 */
public class ValidateExport {
    public static void main(String[] args) throws Exception {
        if (args.length != 3) {
            System.err.println(
                "usage: ValidateExport <export.pdb> <tracks> <playlists>");
            System.exit(2);
        }
        int expectedTracks = Integer.parseInt(args[1]);
        int expectedPlaylists = Integer.parseInt(args[2]);

        try (Database db = new Database(new File(args[0]))) {
            int tracks = db.trackIndex.size();
            int playlists = db.playlistIndex.size();
            int colors = db.colorIndex.size();

            RekordboxPdb.TrackRow track = db.trackIndex.get(1L);
            String title = (track == null) ? null : Database.getText(track.title());

            System.out.println("tracks=" + tracks
                + " playlists=" + playlists
                + " colors=" + colors
                + " firstTrack=" + title);

            if (tracks != expectedTracks) {
                throw new IllegalStateException(
                    "expected " + expectedTracks + " tracks, got " + tracks);
            }
            if (playlists != expectedPlaylists) {
                throw new IllegalStateException(
                    "expected " + expectedPlaylists + " playlists, got " + playlists);
            }
            if (colors == 0) {
                throw new IllegalStateException("colors table is empty");
            }
            if (title == null) {
                throw new IllegalStateException("track 1 not found");
            }
        }
        System.out.println("export.pdb accepted by crate-digger");
    }
}
